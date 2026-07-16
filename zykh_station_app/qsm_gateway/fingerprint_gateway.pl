#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use Encode qw(decode);

$| = 1;

my $PORT = int($ENV{QSM_FINGERPRINT_PORT} || 8086);
my $DRIVER = $ENV{QSM_FINGERPRINT_DRIVER} || '/userdata/zykh_app/scripts/as608.pl';
my $INIT_SCRIPT = $ENV{QSM_FINGERPRINT_INIT} || '/userdata/zykh_app/scripts/init_fingerprint.sh';
my $DEVICE = $ENV{AS608_DEVICE} || '/dev/zykh-fingerprint';

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
    if ($method eq 'POST' && $path eq '/api/fingerprint/delete') {
        my $template_id = valid_template_id($params->{template_id});
        return send_json($client, 200, invalid_template_response()) unless defined $template_id;
        return send_json($client, 200, run_driver(8, 'delete', $template_id));
    }
    return send_json($client, 404, { ok => JSON::PP::false, status => 'not_found', error_message => 'Fingerprint API not found' });
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
