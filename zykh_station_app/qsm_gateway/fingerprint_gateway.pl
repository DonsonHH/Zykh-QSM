#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use Encode qw(decode);
use POSIX qw(setsid);
use Time::HiRes qw(time sleep);

$| = 1;

my $PORT = int($ENV{QSM_FINGERPRINT_PORT} || 8086);
my $DRIVER = $ENV{QSM_FINGERPRINT_DRIVER} || '/userdata/zykh_app/scripts/as608.pl';
my $INIT_SCRIPT = $ENV{QSM_FINGERPRINT_INIT} || '/userdata/zykh_app/scripts/init_fingerprint.sh';
my $DEVICE = $ENV{AS608_DEVICE} || '/dev/zykh-fingerprint';
my $ENROLL_STATE = $ENV{QSM_FINGERPRINT_ENROLL_STATE} || '/tmp/zykh-fingerprint-enroll.json';

my $server = IO::Socket::INET->new(
    LocalHost => '0.0.0.0',
    LocalPort => $PORT,
    Proto => 'tcp',
    Listen => 10,
    Reuse => 1,
) or die "Cannot start fingerprint gateway on port $PORT: $!\n";

print "QSM fingerprint gateway listening on 0.0.0.0:$PORT\n";
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
    send_json($client, 500, { ok => JSON::PP::false, status => 'error', error_message => "$@" }) if $@;
    close $client;
    exit 0;
}

sub route_request {
    my ($client, $request) = @_;
    my $path = $request->{path};
    my $method = $request->{method};
    my $params = $request->{params};

    if ($method eq 'GET' && $path eq '/api/fingerprint/status') {
        return send_json($client, 200, fingerprint_status());
    }
    if ($method eq 'POST' && $path eq '/api/fingerprint/identify') {
        my $timeout = clamp_timeout($params->{timeout}, 5, 60, 45);
        return send_json($client, 200, run_driver($timeout + 10, 'identify', $timeout));
    }
    if ($method eq 'POST' && $path eq '/api/fingerprint/enroll') {
        my $template_id = valid_template_id($params->{template_id});
        return send_json($client, 200, invalid_template_response()) unless defined $template_id;
        my $timeout = clamp_timeout($params->{timeout}, 10, 60, 45);
        return send_json($client, 200, run_driver(($timeout * 3) + 15, 'enroll', $template_id, $timeout));
    }
    if ($method eq 'POST' && $path eq '/api/fingerprint/enroll/start') {
        my $template_id = valid_template_id($params->{template_id});
        return send_json($client, 200, invalid_template_response()) unless defined $template_id;
        my $timeout = clamp_timeout($params->{timeout}, 10, 90, 60);
        return send_json($client, 200, start_enrollment($template_id, $timeout));
    }
    if ($method eq 'GET' && $path eq '/api/fingerprint/enroll/progress') {
        return send_json($client, 200, enrollment_progress($params->{job_id} || ''));
    }
    if ($method eq 'POST' && $path eq '/api/fingerprint/delete') {
        my $template_id = valid_template_id($params->{template_id});
        return send_json($client, 200, invalid_template_response()) unless defined $template_id;
        return send_json($client, 200, run_driver(8, 'delete', $template_id));
    }
    return send_json($client, 404, { ok => JSON::PP::false, status => 'not_found', error_message => 'Fingerprint API not found' });
}

sub start_enrollment {
    my ($template_id, $timeout) = @_;
    my $current = read_enrollment_state();
    if ($current && ($current->{status} || '') eq 'running') {
        my $pid = int($current->{pid} || 0);
        my $age = time() - ($current->{updated_at} || 0);
        if (($pid > 0 && kill(0, $pid)) || $age < 220) {
            return {
                ok => JSON::PP::false,
                status => 'busy',
                event => $current->{event} || 'running',
                job_id => $current->{job_id} || '',
                error_message => '已有指纹录入正在进行，请先完成当前录入。',
            };
        }
    }

    initialize_device() unless -e $DEVICE;
    return { ok => JSON::PP::false, status => 'unavailable', error_message => "指纹设备未就绪：$DEVICE" }
        unless -e $DEVICE;
    return { ok => JSON::PP::false, status => 'unavailable', error_message => "指纹驱动不存在：$DRIVER" }
        unless -f $DRIVER;

    my $job_id = join('-', int(time() * 1000), $$, int(rand(100000)));
    my $state = {
        ok => JSON::PP::true,
        status => 'running',
        event => 'place_finger_first',
        job_id => $job_id,
        template_id => $template_id,
        pid => 0,
        events => [],
        updated_at => time(),
    };
    write_enrollment_state($state);

    my $pid = fork();
    return { ok => JSON::PP::false, status => 'error', error_message => "无法启动录入任务：$!" }
        unless defined $pid;
    if ($pid) {
        $state->{pid} = $pid;
        write_enrollment_state($state);
        return $state;
    }

    $state->{pid} = $$;
    setsid();
    for my $fd (0 .. 255) {
        POSIX::close($fd);
    }
    sleep(0.08);
    run_driver_progress($state, ($timeout * 3) + 20, 'enroll', $template_id, $timeout);
    exit 0;
}

sub enrollment_progress {
    my ($job_id) = @_;
    my $state = read_enrollment_state();
    return { ok => JSON::PP::false, status => 'not_found', error_message => '没有可用的指纹录入任务。' }
        unless $state;
    return { ok => JSON::PP::false, status => 'not_found', error_message => '指纹录入任务不存在或已经过期。' }
        if $job_id eq '' || ($state->{job_id} || '') ne $job_id;
    if (($state->{status} || '') eq 'running') {
        my $pid = int($state->{pid} || 0);
        if ($pid > 0 && !kill(0, $pid)) {
            $state->{ok} = JSON::PP::false;
            $state->{status} = 'error';
            $state->{error_message} = '指纹录入任务意外停止，请重新录入。';
            write_enrollment_state($state);
        }
    }
    return $state;
}

sub run_driver_progress {
    my ($state, $command_timeout, @args) = @_;
    my @events;
    my $exit = -1;
    {
        local $SIG{CHLD} = 'DEFAULT';
        open my $pipe, '-|', 'timeout', int($command_timeout), 'perl', $DRIVER, @args;
        if (!$pipe) {
            $state->{ok} = JSON::PP::false;
            $state->{status} = 'error';
            $state->{error_message} = "无法启动指纹驱动：$!";
            write_enrollment_state($state);
            return;
        }
        while (my $line = <$pipe>) {
            chomp $line;
            my $event = eval { decode_json($line) };
            next unless $event && ref($event) eq 'HASH';
            push @events, $event;
            shift @events while @events > 20;
            $state->{events} = [@events];
            $state->{event} = $event->{event} || $state->{event};
            $state->{updated_at} = time();
            if (!$event->{ok}) {
                $state->{ok} = JSON::PP::false;
                $state->{status} = 'error';
                $state->{error_message} = $event->{error} || '指纹录入失败。';
            } elsif (($event->{event} || '') eq 'enrolled') {
                $state->{ok} = JSON::PP::true;
                $state->{status} = 'enrolled';
                $state->{template_id} = int($event->{id});
            } else {
                $state->{ok} = JSON::PP::true;
                $state->{status} = 'running';
            }
            write_enrollment_state($state);
        }
        close $pipe;
        $exit = $? == -1 ? -1 : ($? >> 8);
    }
    if (!@events) {
        $state->{ok} = JSON::PP::false;
        $state->{status} = $exit == 124 ? 'timeout' : 'error';
        $state->{error_message} = $exit == 124 ? '指纹录入超时，请重新录入。' : '指纹驱动未返回有效结果。';
    } elsif (($state->{status} || '') eq 'running') {
        $state->{ok} = JSON::PP::false;
        $state->{status} = 'error';
        $state->{error_message} = '指纹录入未完整结束，请重新录入。';
    }
    $state->{exit_code} = $exit;
    $state->{updated_at} = time();
    write_enrollment_state($state);
}

sub read_enrollment_state {
    return undef unless -s $ENROLL_STATE;
    open my $fh, '<:raw', $ENROLL_STATE or return undef;
    local $/;
    my $raw = <$fh>;
    close $fh;
    my $state = eval { decode_json($raw || '') };
    return $state && ref($state) eq 'HASH' ? $state : undef;
}

sub write_enrollment_state {
    my ($state) = @_;
    my $temporary = "$ENROLL_STATE.$$";
    open my $fh, '>:raw', $temporary or return 0;
    print {$fh} encode_json($state);
    close $fh;
    rename $temporary, $ENROLL_STATE;
    return 1;
}

sub fingerprint_status {
    my $result = run_driver(8, 'status');
    $result->{status} = $result->{ok} ? 'available' : 'unavailable';
    $result->{device} = $DEVICE;
    return $result;
}

sub run_driver {
    my ($command_timeout, @args) = @_;
    initialize_device() unless -e $DEVICE;
    return {
        ok => JSON::PP::false,
        status => 'unavailable',
        error_message => "指纹设备未就绪：$DEVICE",
    } unless -e $DEVICE;
    return {
        ok => JSON::PP::false,
        status => 'unavailable',
        error_message => "指纹驱动不存在：$DRIVER",
    } unless -f $DRIVER;

    my @events;
    my $stderr = '';
    my $exit = -1;
    {
        local $SIG{CHLD} = 'DEFAULT';
        open my $pipe, '-|', 'timeout', int($command_timeout), 'perl', $DRIVER, @args
            or return { ok => JSON::PP::false, status => 'error', error_message => "无法启动指纹驱动：$!" };
        while (my $line = <$pipe>) {
            chomp $line;
            my $event = eval { decode_json($line) };
            push @events, $event if $event && ref($event) eq 'HASH';
        }
        close $pipe;
        $exit = $? == -1 ? -1 : ($? >> 8);
    }

    if (!@events) {
        return {
            ok => JSON::PP::false,
            status => $exit == 124 ? 'timeout' : 'error',
            error_message => $exit == 124 ? '指纹操作超时，请重新放置手指。' : '指纹驱动未返回有效结果。',
            exit_code => $exit,
        };
    }

    my $result = { %{$events[-1]} };
    pop @events;
    $result->{events} = \@events;
    $result->{status} ||= $result->{matched} ? 'matched' : $result->{event} || ($result->{ok} ? 'complete' : 'error');
    $result->{exit_code} = $exit;
    return $result;
}

sub initialize_device {
    return unless -x $INIT_SCRIPT;
    local $SIG{CHLD} = 'DEFAULT';
    system('sh', $INIT_SCRIPT, 'start');
}

sub valid_template_id {
    my ($value) = @_;
    return undef unless defined $value && $value =~ /\A\d+\z/;
    my $id = int($value);
    return undef if $id < 0 || $id > 299;
    return $id;
}

sub invalid_template_response {
    return { ok => JSON::PP::false, status => 'invalid', error_message => '指纹模板编号必须为 0 到 299。' };
}

sub clamp_timeout {
    my ($value, $minimum, $maximum, $fallback) = @_;
    my $timeout = defined($value) && $value =~ /\A\d+\z/ ? int($value) : $fallback;
    $timeout = $minimum if $timeout < $minimum;
    $timeout = $maximum if $timeout > $maximum;
    return $timeout;
}

sub read_request {
    my ($client) = @_;
    my $first = <$client>;
    return undef unless defined $first;
    $first =~ s/\r?\n$//;
    my ($method, $target) = split /\s+/, $first;
    return undef unless $method && $target;
    my %headers;
    while (my $line = <$client>) {
        last if $line =~ /^\r?\n$/;
        $line =~ s/\r?\n$//;
        my ($key, $value) = split /:\s*/, $line, 2;
        $headers{lc $key} = $value if defined $key;
    }
    my $body = '';
    my $length = int($headers{'content-length'} || 0);
    read($client, $body, $length) if $length > 0;
    my ($path, $query) = split /\?/, $target, 2;
    my $params = parse_form($query || '');
    if ($body ne '') {
        if (($headers{'content-type'} || '') =~ /application\/json/) {
            my $decoded = eval { decode_json($body) };
            $params = $decoded if $decoded && ref($decoded) eq 'HASH';
        } else {
            $params = parse_form($body);
        }
    }
    return { method => uc($method), path => $path || '/', params => $params };
}

sub parse_form {
    my ($text) = @_;
    my %params;
    for my $pair (split /&/, $text || '') {
        my ($key, $value) = split /=/, $pair, 2;
        next unless defined $key;
        $params{url_decode($key)} = url_decode($value || '');
    }
    return \%params;
}

sub url_decode {
    my ($value) = @_;
    $value =~ tr/+/ /;
    $value =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/eg;
    return decode('UTF-8', $value);
}

sub send_json {
    my ($client, $status, $payload) = @_;
    my $body = encode_json($payload);
    my $reason = $status == 200 ? 'OK' : $status == 404 ? 'Not Found' : 'Internal Server Error';
    print {$client} "HTTP/1.1 $status $reason\r\n";
    print {$client} "Content-Type: application/json; charset=utf-8\r\n";
    print {$client} "Access-Control-Allow-Origin: *\r\n";
    print {$client} "Cache-Control: no-store\r\n";
    print {$client} "Connection: close\r\n";
    print {$client} 'Content-Length: ' . length($body) . "\r\n\r\n";
    print {$client} $body;
}
