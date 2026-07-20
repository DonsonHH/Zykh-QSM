#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use Fcntl qw(O_RDWR O_NOCTTY LOCK_EX LOCK_NB);
use POSIX qw(strftime setsid tcflush TCIFLUSH);
use Time::HiRes qw(time sleep);

$| = 1;

my $PORT = int($ENV{QSM_VITALS_PORT} || 8085);
my $HOME = $ENV{QSM_VITALS_HOME} || '/userdata/qsm-vitals';
my $DATA = "$HOME/data";
my $UART_READER = $ENV{QSM_VITALS_UART_READER} || '/userdata/zykh_app/scripts/read_vitals_uart8.pl';
my $GY_READER = $ENV{QSM_GY614_READER} || '/userdata/medical_assistant/scripts/read_gy614_uart4.pl';
my $GY_DEVICE = $ENV{GY614_UART} || '/dev/ttyS4';
my $UART_DEVICE = $ENV{VITALS_UART_DEVICE} || '/dev/ttyS8';
# The module needs 5-10 seconds to initialize its algorithm after a cold start,
# then produces an update about every 1.28 seconds. Stable warm readings still
# exit early in read_vitals_uart8.pl.
my $MEASURE_TIMEOUT = int($ENV{QSM_VITALS_MEASURE_TIMEOUT} || 18);
my $STABLE_FRAMES = int($ENV{QSM_VITALS_STABLE_FRAMES} || 2);
$STABLE_FRAMES = 2 if $STABLE_FRAMES < 2;
my $SPO2_GRACE = int($ENV{QSM_VITALS_SPO2_GRACE_SECONDS} || 8);
$SPO2_GRACE = 0 if $SPO2_GRACE < 0;
my $INITIAL_STABILIZATION_SECONDS = int($ENV{QSM_VITALS_INITIAL_STABILIZATION_SECONDS} || 8);
$INITIAL_STABILIZATION_SECONDS = 5 if $INITIAL_STABILIZATION_SECONDS < 5;
my $PREPARE_TTL = int($ENV{QSM_VITALS_PREPARE_TTL_SECONDS} || 45);
my $CURRENT = "$DATA/current.json";
my $PREPARED = "$DATA/prepared.json";

system('mkdir', '-p', $DATA) == 0 or die "Cannot create $DATA\n";

my $server = IO::Socket::INET->new(
    LocalHost => '0.0.0.0',
    LocalPort => $PORT,
    Proto => 'tcp',
    Listen => 10,
    Reuse => 1,
) or die "Cannot start vitals gateway on port $PORT: $!\n";

print "QSM vitals gateway listening on 0.0.0.0:$PORT\n";
$SIG{CHLD} = 'IGNORE';

while (my $client = $server->accept()) {
    my $pid = fork();
    if (!defined $pid) {
        close $client;
        next;
    }
    if ($pid) {
        close $client;
        next;
    }
    eval {
        $client->autoflush(1);
        my $request = read_request($client);
        route_request($client, $request) if $request;
    };
    send_json($client, 500, session_error('', 'failed', "$@")) if $@;
    close $client;
    exit 0;
}

sub route_request {
    my ($client, $request) = @_;
    my $path = $request->{path};
    my $method = $request->{method};
    if ($method eq 'POST' && $path eq '/api/vitals/prepare') {
        return send_json($client, 200, prepare_hardware());
    }
    if ($method eq 'POST' && $path eq '/api/vitals/session/start') {
        return send_json($client, 200, start_session($request->{params}));
    }
    if ($method eq 'GET' && $path eq '/api/vitals/session/status') {
        return send_json($client, 200, session_status($request->{params}{session_id} || ''));
    }
    if ($method eq 'POST' && $path eq '/api/vitals/session/cancel') {
        return send_json($client, 200, cancel_session($request->{params}{session_id} || ''));
    }
    return send_json($client, 404, session_error('', 'not_found', 'Vitals session API not found'));
}

sub start_session {
    my ($params) = @_;
    $params ||= {};
    my $current = read_json($CURRENT);
    if ($current && active_status($current->{status}) && process_alive($current->{worker_pid})) {
        my $replace_active = ($params->{replace_active} || '') =~ /^(?:1|true|yes)$/i;
        return busy_session($current) unless $replace_active;
        my $stopped = stop_active_session($current, 'replaced');
        return $stopped unless $stopped->{ok};
    }

    my ($prewarmed, $prewarm_age) = consume_prepared();
    my $session_id = join('-', 'vitals', int(time() * 1000), int(rand(100000)));
    my $state_file = state_file($session_id);
    my $started_at = now_text();
    my $state = {
        ok => JSON::PP::true,
        mode => 'real',
        session_id => $session_id,
        status => 'starting',
        hardware_started => JSON::PP::false,
        started_at => $started_at,
        updated_at => $started_at,
        worker_pid => 0,
        prewarmed => $prewarmed ? JSON::PP::true : JSON::PP::false,
        prewarm_age => sprintf('%.2f', $prewarm_age) + 0,
    };
    write_json_atomic($state_file, $state);
    write_json_atomic($CURRENT, $state);

    my $pid = fork();
    return session_error($session_id, 'failed', "Cannot fork vitals worker: $!") unless defined $pid;
    if (!$pid) {
        $SIG{CHLD} = 'DEFAULT';
        setsid();
        run_measurement($session_id, $started_at, $prewarmed, $prewarm_age);
        exit 0;
    }
    my $fresh_state = read_json($state_file) || $state;
    $fresh_state->{worker_pid} = $pid;
    write_json_atomic($state_file, $fresh_state);
    write_json_atomic($CURRENT, $fresh_state);

    my $deadline = time() + 2.5;
    while (time() < $deadline) {
        my $fresh = read_json($state_file) || {};
        if ($fresh->{hardware_started} || ($fresh->{status} || '') eq 'failed') {
            $fresh->{worker_pid} ||= $pid;
            return $fresh;
        }
        sleep(0.05);
    }
    write_text(cancel_file($session_id), now_text());
    return session_error($session_id, 'failed', 'Vitals hardware did not acknowledge start command');
}

sub run_measurement {
    my ($session_id, $started_at, $prewarmed, $prewarm_age) = @_;
    my $started_epoch = time();
    my $state_file = state_file($session_id);
    my $cancel_file = cancel_file($session_id);
    my $uart_output = "$DATA/$session_id-uart.json";
    my $gy_output = "$DATA/$session_id-gy614.json";
    unlink $cancel_file if -e $cancel_file;
    unlink $uart_output if -e $uart_output;
    unlink $gy_output if -e $gy_output;

    my $minimum_measurement_seconds = $INITIAL_STABILIZATION_SECONDS;
    if ($prewarmed) {
        $minimum_measurement_seconds = $INITIAL_STABILIZATION_SECONDS - ($prewarm_age || 0);
        # Two 1.28-second update periods are still required after the user starts.
        $minimum_measurement_seconds = 3 if $minimum_measurement_seconds < 3;
    }

    my $uart_cmd = join(' ',
        'perl', shell_quote($UART_READER),
        '--timeout', $MEASURE_TIMEOUT,
        '--stable-frames', $STABLE_FRAMES,
        '--spo2-grace', $SPO2_GRACE,
        '--minimum-measurement-seconds', $minimum_measurement_seconds,
        '--minimum-contact-seconds', 2.6,
        ($prewarmed ? ('--prewarmed') : ()),
        '--output', shell_quote($uart_output),
        '--state-file', shell_quote($state_file),
        '--cancel-file', shell_quote($cancel_file),
        '--session-id', shell_quote($session_id),
    );
    my $gy_cmd = -f $GY_READER
        ? join(' ', 'perl', shell_quote($GY_READER), shell_quote($GY_DEVICE), shell_quote($gy_output))
        : 'true';
    my $shell = "($uart_cmd >/dev/null 2>&1) & uart=\$!; " .
                "($gy_cmd >/dev/null 2>&1) & gy=\$!; " .
                'wait $uart; uart_rc=$?; wait $gy; gy_rc=$?; exit $uart_rc';
    system('sh', '-c', $shell);

    my $uart = read_json($uart_output) || {};
    my $gy = read_json($gy_output) || {};
    my $temperature = first_number($gy, qw(body_temp_c target_temp_c temperature temperature_c));
    if (!defined $temperature && ref($gy->{temperature}) eq 'HASH') {
        $temperature = first_number($gy->{temperature}, qw(body_temp_c target_temp_c temperature_c));
    }
    my $heart_rate = first_number($uart, qw(heart_rate_bpm heart_rate));
    my $spo2 = first_number($uart, qw(spo2_percent spo2));
    my $cancelled = -e $cancel_file;
    my $complete = !$cancelled && $uart->{stable_core}
        && defined($heart_rate) && $heart_rate > 0
        && defined($spo2) && $spo2 > 0
        && defined($temperature) && $temperature > 0;
    my $status = $cancelled ? 'cancelled' : $complete ? 'complete' : 'failed';
    my $error = '';
    if (!$complete && !$cancelled) {
        if ((!defined($heart_rate) || $heart_rate <= 0) && (!defined($spo2) || $spo2 <= 0)) {
            $error = $uart->{finger_detected}
                ? '已检测到手指，心率与血氧仍未稳定，请保持不动后重试。'
                : '未检测到稳定的手指信号，请用指腹完整覆盖传感器后重试。';
        } elsif (!defined($spo2) || $spo2 <= 0) {
            $error = '已读取到心率，血氧仍未稳定，请保持手指不动后重试。';
        } elsif (!defined($heart_rate) || $heart_rate <= 0) {
            $error = '已读取到血氧，心率仍未稳定，请保持手指不动后重试。';
        } elsif (!$uart->{stable_core}) {
            $error = '心率和血氧出现过读数，但近期信号不连续，请保持手指完整覆盖后重试。';
        } elsif (!defined($temperature) || $temperature <= 0) {
            $error = '心率与血氧已完成，额温未读取，请对准额温传感器后重试。';
        }
    }
    my $state = {
        ok => $complete ? JSON::PP::true : JSON::PP::false,
        mode => 'real',
        session_id => $session_id,
        status => $status,
        hardware_started => JSON::PP::true,
        elapsed_seconds => sprintf('%.2f', time() - $started_epoch) + 0,
        temperature => $temperature,
        heart_rate => $heart_rate,
        spo2 => $spo2,
        systolic_pressure => positive_or_undef($uart->{systolic_pressure}),
        diastolic_pressure => positive_or_undef($uart->{diastolic_pressure}),
        respiratory_rate => positive_or_undef($uart->{respiratory_rate}),
        microcirculation => positive_or_undef($uart->{microcirculation}),
        fatigue => positive_or_undef($uart->{fatigue}),
        rr_interval => positive_or_undef($uart->{rr_interval}),
        hrv_sdnn => positive_or_undef($uart->{hrv_sdnn}),
        hrv_rmssd => positive_or_undef($uart->{hrv_rmssd}),
        body_temperature => first_number($uart, qw(body_temperature_c body_temperature)),
        ambient_temperature => first_number($uart, qw(ambient_temperature_c ambient_temperature)),
        reference_ready => $uart->{reference_ready} ? JSON::PP::true : JSON::PP::false,
        finger_detected => $uart->{finger_detected} ? JSON::PP::true : JSON::PP::false,
        quality => $uart->{quality} || undef,
        message => $uart->{message} || undef,
        sample_count => int($uart->{sample_count} || 0),
        valid_frame_count => int($uart->{valid_frame_count} || 0),
        communication_status => $uart->{communication_status} || undef,
        stable_core => $uart->{stable_core} ? JSON::PP::true : JSON::PP::false,
        spo2_stabilization_extended => $uart->{spo2_stabilization_extended}
            ? JSON::PP::true
            : JSON::PP::false,
        contact_frame_count => int($uart->{contact_frame_count} || 0),
        heart_rate_frame_count => int($uart->{heart_rate_frame_count} || 0),
        spo2_frame_count => int($uart->{spo2_frame_count} || 0),
        first_heart_rate_frame => $uart->{first_heart_rate_frame},
        first_spo2_frame => $uart->{first_spo2_frame},
        source => 'UART8-vitals-24B+GY-614',
        started_at => $started_at,
        updated_at => now_text(),
        measured_at => now_text(),
        error_message => $error || undef,
        worker_pid => $$,
        prewarmed => $prewarmed ? JSON::PP::true : JSON::PP::false,
        prewarm_age => sprintf('%.2f', $prewarm_age || 0) + 0,
        minimum_measurement_seconds => sprintf('%.2f', $minimum_measurement_seconds) + 0,
    };
    write_json_atomic($state_file, $state);
    write_json_atomic($CURRENT, $state);
}

sub prepare_hardware {
    my $existing = read_json($PREPARED) || {};
    my $existing_age = time() - ($existing->{prepared_epoch} || 0);
    if ($existing->{hardware_started} && $existing_age >= 0 && $existing_age <= $PREPARE_TTL) {
        $existing->{reused} = JSON::PP::true;
        return $existing;
    }
    my $current = read_json($CURRENT);
    if ($current && active_status($current->{status}) && process_alive($current->{worker_pid})) {
        return {
            ok => JSON::PP::true,
            mode => 'real',
            status => 'in_progress',
            hardware_started => JSON::PP::true,
            prepared => JSON::PP::false,
            updated_at => now_text(),
        };
    }
    my $result = write_uart_command(0x24, reset_first => 1);
    return $result unless $result->{ok};

    my $token = join('-', int(time() * 1000), int(rand(100000)));
    my $prepared = {
        ok => JSON::PP::true,
        mode => 'real',
        status => 'ready',
        hardware_started => JSON::PP::true,
        prepared => JSON::PP::true,
        prepared_epoch => time() + 0,
        prepared_at => now_text(),
        token => $token,
    };
    write_json_atomic($PREPARED, $prepared);

    my $guard = fork();
    if (defined $guard && !$guard) {
        $SIG{CHLD} = 'DEFAULT';
        sleep($PREPARE_TTL);
        my $latest = read_json($PREPARED) || {};
        my $active = read_json($CURRENT) || {};
        if (($latest->{token} || '') eq $token && !active_status($active->{status})) {
            write_uart_command(0x2A);
            unlink $PREPARED;
        }
        exit 0;
    }
    return $prepared;
}

sub consume_prepared {
    my $prepared = read_json($PREPARED) || {};
    my $age = time() - ($prepared->{prepared_epoch} || 0);
    my $ready = $prepared->{hardware_started} && $age >= 0 && $age <= $PREPARE_TTL;
    unlink $PREPARED if -e $PREPARED;
    return ($ready ? 1 : 0, $ready ? $age : 0);
}

sub write_uart_command {
    my ($command, %options) = @_;
    return session_error('', 'failed', "Vitals UART device does not exist: $UART_DEVICE")
        unless -e $UART_DEVICE;
    my $lock_path = $ENV{VITALS_UART_LOCK_FILE} || '/tmp/zykh-vitals-uart8.lock';
    open my $lock_fh, '>>', $lock_path
        or return session_error('', 'failed', "Cannot open UART lock: $!");
    if (!flock($lock_fh, LOCK_EX | LOCK_NB)) {
        close $lock_fh;
        return session_error('', 'busy', 'Vitals UART is already in use');
    }
    my @stty = (
        'stty', '-F', $UART_DEVICE, '9600', 'cs8', '-cstopb', '-parenb',
        '-ixon', '-ixoff', '-crtscts', 'raw', '-echo', 'min', '0', 'time', '10',
    );
    my $stty_rc;
    {
        # The HTTP server ignores SIGCHLD for request workers. Temporarily use
        # the default handler so system() can collect stty's real exit status.
        local $SIG{CHLD} = 'DEFAULT';
        $stty_rc = system(@stty);
    }
    if ($stty_rc != 0) {
        close $lock_fh;
        return session_error('', 'failed', "Failed to configure $UART_DEVICE");
    }
    my $uart;
    if (!sysopen($uart, $UART_DEVICE, O_RDWR | O_NOCTTY)) {
        close $lock_fh;
        return session_error('', 'failed', "Cannot open $UART_DEVICE: $!");
    }
    binmode($uart);
    if ($options{reset_first}) {
        syswrite($uart, pack('C', 0x2A));
        sleep(0.12);
        tcflush(fileno($uart), TCIFLUSH);
    }
    my $written = syswrite($uart, pack('C', $command));
    close $uart;
    close $lock_fh;
    return session_error('', 'failed', "Failed to write UART command 0x" . sprintf('%02X', $command))
        unless defined($written) && $written == 1;
    return {
        ok => JSON::PP::true,
        mode => 'real',
        status => 'ready',
        hardware_started => JSON::PP::true,
        updated_at => now_text(),
    };
}

sub session_status {
    my ($session_id) = @_;
    return session_error('', 'not_found', 'session_id is required') unless $session_id =~ /^vitals-[A-Za-z0-9-]+$/;
    my $state = read_json(state_file($session_id));
    return session_error($session_id, 'not_found', 'Vitals session not found') unless $state;
    return $state;
}

sub cancel_session {
    my ($session_id) = @_;
    my $state = session_status($session_id);
    return $state if ($state->{status} || '') eq 'not_found';
    if (active_status($state->{status})) {
        return stop_active_session($state, 'cancelled');
    }
    return $state;
}

sub stop_active_session {
    my ($state, $reason) = @_;
    my $session_id = $state->{session_id} || '';
    my $pid = int($state->{worker_pid} || 0);
    return session_error($session_id, 'failed', 'Cannot stop an unnamed vitals session')
        unless $session_id =~ /^vitals-[A-Za-z0-9-]+$/;

    write_text(cancel_file($session_id), now_text());
    my $deadline = time() + 2.6;
    while ($pid > 0 && process_alive($pid) && time() < $deadline) {
        sleep(0.08);
    }
    if ($pid > 0 && process_alive($pid)) {
        # The measurement worker creates its own process group. Stop the UART
        # reader and temperature child together so the serial lock is released.
        kill('TERM', -$pid);
        my $term_deadline = time() + 1.2;
        sleep(0.06) while process_alive($pid) && time() < $term_deadline;
        kill('KILL', -$pid) if process_alive($pid);
    }

    my $stop = write_uart_command(0x2A);
    if (!$stop->{ok} && ($stop->{status} || '') eq 'busy') {
        sleep(0.25);
        $stop = write_uart_command(0x2A);
    }
    my $latest = read_json(state_file($session_id)) || $state;
    $latest->{ok} = JSON::PP::true;
    $latest->{status} = 'cancelled';
    $latest->{hardware_started} = JSON::PP::false;
    $latest->{worker_pid} = 0;
    $latest->{cancel_reason} = $reason || 'cancelled';
    $latest->{updated_at} = now_text();
    $latest->{error_message} = undef;
    write_json_atomic(state_file($session_id), $latest);
    write_json_atomic($CURRENT, $latest);
    return $latest;
}

sub busy_session {
    my ($current) = @_;
    my %copy = %{$current || {}};
    $copy{ok} = JSON::PP::false;
    $copy{status} = 'busy';
    $copy{error_message} = '上一轮体征测量尚未结束，请稍后重试。';
    return \%copy;
}

sub active_status {
    my ($status) = @_;
    return ($status || '') =~ /^(starting|waiting_finger|stabilizing)$/ ? 1 : 0;
}

sub process_alive {
    my ($pid) = @_;
    return $pid && $pid =~ /^\d+$/ && kill(0, $pid) ? 1 : 0;
}

sub state_file { return "$DATA/$_[0]-state.json"; }
sub cancel_file { return "$DATA/$_[0]-cancel"; }

sub first_number {
    my ($payload, @keys) = @_;
    for my $key (@keys) {
        next unless exists $payload->{$key};
        my $value = $payload->{$key};
        return $value + 0 if defined $value && $value =~ /^-?\d+(?:\.\d+)?$/;
    }
    return undef;
}

sub positive_or_undef {
    my ($value) = @_;
    return undef unless defined $value && $value =~ /^-?\d+(?:\.\d+)?$/ && $value > 0;
    return $value + 0;
}

sub session_error {
    my ($session_id, $status, $message) = @_;
    return {
        ok => JSON::PP::false,
        mode => 'real',
        session_id => $session_id || '',
        status => $status,
        hardware_started => JSON::PP::false,
        updated_at => now_text(),
        error_message => $message,
    };
}

sub read_request {
    my ($client) = @_;
    my $first = <$client>;
    return undef unless defined $first;
    $first =~ s/\r?\n$//;
    my ($method, $target) = split /\s+/, $first;
    my %headers;
    while (my $line = <$client>) {
        last if $line =~ /^\r?\n$/;
        $line =~ s/\r?\n$//;
        my ($key, $value) = split /:\s*/, $line, 2;
        $headers{lc($key || '')} = $value if defined $key;
    }
    my $body = '';
    read($client, $body, int($headers{'content-length'} || 0)) if ($headers{'content-length'} || 0) > 0;
    my ($path, $query) = split /\?/, $target || '/', 2;
    my $params = parse_form($query || '');
    if ($body ne '') {
        if (($headers{'content-type'} || '') =~ /application\/json/) {
            my $decoded = eval { decode_json($body) };
            %{$params} = (%{$params}, %{$decoded}) if $decoded && ref($decoded) eq 'HASH';
        } else {
            %{$params} = (%{$params}, %{parse_form($body)});
        }
    }
    return { method => uc($method || ''), path => $path || '/', params => $params };
}

sub parse_form {
    my ($text) = @_;
    my %out;
    for my $part (split /&/, $text || '') {
        my ($key, $value) = split /=/, $part, 2;
        next unless defined $key;
        for ($key, $value) {
            $_ = '' unless defined $_;
            tr/+/ /;
            s/%([0-9A-Fa-f]{2})/chr(hex($1))/eg;
        }
        $out{$key} = $value;
    }
    return \%out;
}

sub send_json {
    my ($client, $status, $payload) = @_;
    my $body = encode_json($payload);
    my $reason = $status == 404 ? 'Not Found' : $status == 500 ? 'Internal Server Error' : 'OK';
    print {$client} "HTTP/1.1 $status $reason\r\n";
    print {$client} "Content-Type: application/json; charset=utf-8\r\n";
    print {$client} "Connection: close\r\n";
    print {$client} 'Content-Length: ' . length($body) . "\r\n\r\n";
    print {$client} $body;
}

sub read_json {
    my ($path) = @_;
    return undef unless -s $path;
    open my $fh, '<:raw', $path or return undef;
    local $/;
    my $raw = <$fh>;
    close $fh;
    my $payload = eval { decode_json($raw || '') };
    return $payload && ref($payload) eq 'HASH' ? $payload : undef;
}

sub write_json_atomic {
    my ($path, $payload) = @_;
    my $temporary = "$path.$$";
    open my $fh, '>:raw', $temporary or return 0;
    print {$fh} encode_json($payload);
    close $fh;
    rename $temporary, $path;
    return 1;
}

sub write_text {
    my ($path, $text) = @_;
    open my $fh, '>:raw', $path or return 0;
    print {$fh} $text;
    close $fh;
    return 1;
}

sub shell_quote {
    my ($value) = @_;
    $value =~ s/'/'"'"'/g;
    return "'$value'";
}

sub now_text { return strftime('%Y-%m-%dT%H:%M:%S%z', localtime); }
