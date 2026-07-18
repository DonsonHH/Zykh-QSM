#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use POSIX qw(strftime setsid);
use Time::HiRes qw(time sleep);

$| = 1;

my $PORT = int($ENV{QSM_VITALS_PORT} || 8085);
my $HOME = $ENV{QSM_VITALS_HOME} || '/userdata/qsm-vitals';
my $DATA = "$HOME/data";
my $UART_READER = $ENV{QSM_VITALS_UART_READER} || '/userdata/zykh_app/scripts/read_vitals_uart8.pl';
my $GY_READER = $ENV{QSM_GY614_READER} || '/userdata/medical_assistant/scripts/read_gy614_uart4.pl';
my $GY_DEVICE = $ENV{GY614_UART} || '/dev/ttyS4';
my $MEASURE_TIMEOUT = int($ENV{QSM_VITALS_MEASURE_TIMEOUT} || 10);
my $CURRENT = "$DATA/current.json";

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
    if ($method eq 'POST' && $path eq '/api/vitals/session/start') {
        return send_json($client, 200, start_session());
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
    my $current = read_json($CURRENT);
    if ($current && active_status($current->{status}) && process_alive($current->{worker_pid})) {
        $current->{ok} = JSON::PP::false;
        $current->{error_message} = 'A vitals measurement is already in progress';
        return $current;
    }

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
    };
    write_json_atomic($state_file, $state);
    write_json_atomic($CURRENT, $state);

    my $pid = fork();
    return session_error($session_id, 'failed', "Cannot fork vitals worker: $!") unless defined $pid;
    if (!$pid) {
        $SIG{CHLD} = 'DEFAULT';
        setsid();
        run_measurement($session_id, $started_at);
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
    my ($session_id, $started_at) = @_;
    my $started_epoch = time();
    my $state_file = state_file($session_id);
    my $cancel_file = cancel_file($session_id);
    my $uart_output = "$DATA/$session_id-uart.json";
    my $gy_output = "$DATA/$session_id-gy614.json";
    unlink $cancel_file if -e $cancel_file;
    unlink $uart_output if -e $uart_output;
    unlink $gy_output if -e $gy_output;

    my $uart_cmd = join(' ',
        'perl', shell_quote($UART_READER),
        '--timeout', $MEASURE_TIMEOUT,
        '--stable-frames', 2,
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
    my $complete = !$cancelled && defined($heart_rate) && $heart_rate > 0
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
        contact_frame_count => int($uart->{contact_frame_count} || 0),
        heart_rate_frame_count => int($uart->{heart_rate_frame_count} || 0),
        spo2_frame_count => int($uart->{spo2_frame_count} || 0),
        source => 'UART8-vitals-24B+GY-614',
        started_at => $started_at,
        updated_at => now_text(),
        measured_at => now_text(),
        error_message => $error || undef,
        worker_pid => $$,
    };
    write_json_atomic($state_file, $state);
    write_json_atomic($CURRENT, $state);
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
        write_text(cancel_file($session_id), now_text());
        $state->{ok} = JSON::PP::true;
        $state->{status} = 'cancelled';
        $state->{updated_at} = now_text();
        write_json_atomic(state_file($session_id), $state);
        write_json_atomic($CURRENT, $state);
    }
    return $state;
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
