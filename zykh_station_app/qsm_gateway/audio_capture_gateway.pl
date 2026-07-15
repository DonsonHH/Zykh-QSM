#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use MIME::Base64 qw(encode_base64);
use Encode qw(decode);

$| = 1;

my $PORT = int($ENV{QSM_AUDIO_CAPTURE_PORT} || 8082);
my $MAX_DURATION = int($ENV{QSM_AUDIO_CAPTURE_MAX_SECONDS} || 45);

my $server = IO::Socket::INET->new(
    LocalHost => '0.0.0.0',
    LocalPort => $PORT,
    Proto => 'tcp',
    Listen => 10,
    Reuse => 1,
) or die "Cannot start audio capture gateway on port $PORT: $!\n";

print "QSM audio capture gateway listening on 0.0.0.0:$PORT\n";
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
    send_json($client, 500, { ok => JSON::PP::false, error_message => "$@" }) if $@;
    close $client;
    exit 0;
}

sub route_request {
    my ($client, $request) = @_;
    my $path = $request->{path};
    my $method = $request->{method};

    if ($method eq 'GET' && $path eq '/api/audio/capture/status') {
        return send_json($client, 200, capture_status());
    }
    if ($method eq 'GET' && $path eq '/api/audio/capture/stream') {
        return send_pcm_stream($client, $request->{params});
    }
    if ($method eq 'POST' && $path eq '/api/audio/capture/record') {
        return send_json($client, 200, record_audio($request->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/audio/capture/volume') {
        return send_json($client, 200, set_capture_volume($request->{params}));
    }
    return send_json($client, 404, { ok => JSON::PP::false, error_message => 'Audio capture API not found' });
}

sub capture_status {
    my ($device, $card) = detect_camera_microphone();
    my $available = $device ne '';
    my $volume = $available ? read_capture_volume($card) : undef;
    return {
        ok => $available ? JSON::PP::true : JSON::PP::false,
        status => $available ? 'available' : 'unavailable',
        source => 'FF Camera',
        device => $device || undef,
        card => $card ne '' ? $card : undef,
        rate => 16000,
        channels => 1,
        volume => $volume,
        error_message => $available ? undef : '未检测到 FF Camera 麦克风。',
    };
}

sub send_pcm_stream {
    my ($client, $params) = @_;
    my ($device) = detect_camera_microphone();
    return send_json($client, 503, { ok => JSON::PP::false, error_message => '未检测到 FF Camera 麦克风。' }) if $device eq '';

    my $rate = int($params->{rate} || 16000);
    $rate = 16000 unless $rate == 8000 || $rate == 16000 || $rate == 24000 || $rate == 48000;
    my $duration = int($params->{duration} || $MAX_DURATION);
    $duration = 1 if $duration < 1;
    $duration = $MAX_DURATION if $duration > $MAX_DURATION;
    my @command = ('arecord', '-q', '-D', $device, '-t', 'raw', '-f', 'S16_LE', '-r', $rate, '-c', '1', '-d', $duration);
    open my $audio, '-|', @command
        or return send_json($client, 500, { ok => JSON::PP::false, error_message => "无法启动麦克风采集：$!" });

    print {$client} "HTTP/1.1 200 OK\r\n";
    print {$client} "Content-Type: application/octet-stream\r\n";
    print {$client} "Cache-Control: no-store\r\n";
    print {$client} "X-Audio-Format: S16_LE\r\n";
    print {$client} "X-Audio-Rate: $rate\r\n";
    print {$client} "X-Audio-Channels: 1\r\n";
    print {$client} "Connection: close\r\n\r\n";
    binmode $client, ':raw';
    binmode $audio, ':raw';
    local $SIG{PIPE} = 'IGNORE';
    my $buffer;
    while (read($audio, $buffer, 3200)) {
        last unless print {$client} $buffer;
    }
    close $audio;
}

sub record_audio {
    my ($params) = @_;
    my ($device) = detect_camera_microphone();
    return { ok => JSON::PP::false, status => 'unavailable', error_message => '未检测到 FF Camera 麦克风。' } if $device eq '';

    my $duration = int($params->{duration} || 4);
    $duration = 1 if $duration < 1;
    $duration = 10 if $duration > 10;
    my $rate = 16000;
    my $path = "/tmp/zykh-qsm-mic-$$.wav";
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', $duration + 3, 'arecord', '-q', '-D', $device, '-t', 'wav', '-f', 'S16_LE', '-r', $rate, '-c', '1', '-d', $duration, $path);
    }
    if ($rc != 0 || !-s $path) {
        unlink $path;
        return { ok => JSON::PP::false, status => 'error', error_message => 'QSM 麦克风录音失败。' };
    }
    open my $file, '<:raw', $path or return { ok => JSON::PP::false, status => 'error', error_message => "读取录音失败：$!" };
    local $/;
    my $audio = <$file>;
    close $file;
    unlink $path;
    return {
        ok => JSON::PP::true,
        status => 'captured',
        source => 'FF Camera',
        format => 'wav',
        rate => $rate,
        channels => 1,
        duration => $duration,
        audio_base64 => encode_base64($audio, ''),
    };
}

sub set_capture_volume {
    my ($params) = @_;
    my ($device, $card) = detect_camera_microphone();
    return { ok => JSON::PP::false, status => 'unavailable', error_message => '未检测到 FF Camera 麦克风。' } if $device eq '';
    my $volume = int($params->{volume} || 0);
    $volume = 0 if $volume < 0;
    $volume = 100 if $volume > 100;
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('amixer', '-q', '-c', $card, 'sset', 'Mic', "$volume%", 'cap');
    }
    return {
        ok => $rc == 0 ? JSON::PP::true : JSON::PP::false,
        status => $rc == 0 ? 'updated' : 'error',
        volume => $volume,
        source => 'FF Camera',
        error_message => $rc == 0 ? undef : 'QSM 麦克风音量调整失败。',
    };
}

sub detect_camera_microphone {
    my $forced = trim($ENV{QSM_AUDIO_CAPTURE_DEVICE} || '');
    if ($forced ne '') {
        my $card = trim($ENV{QSM_AUDIO_CAPTURE_CARD} || 'Camera');
        return ($forced, $card);
    }
    my $cards = `arecord -l 2>/dev/null`;
    if ($cards =~ /card\s+(\d+):\s+Camera\b[^\n]*device\s+(\d+):/i) {
        return ('plughw:Camera,' . $2, 'Camera');
    }
    if ($cards =~ /card\s+(\d+):[^\n]*(?:FF Camera|USB Audio)[^\n]*device\s+(\d+):/i) {
        return ('plughw:' . $1 . ',' . $2, $1);
    }
    return ('', '');
}

sub read_capture_volume {
    my ($card) = @_;
    my $output = `amixer -c '$card' get Mic 2>/dev/null`;
    my @values = $output =~ /\[(\d+)%\]/g;
    return @values ? int($values[-1]) : undef;
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
    my $reason = $status == 200 ? 'OK' : $status == 404 ? 'Not Found' : $status == 503 ? 'Service Unavailable' : 'Internal Server Error';
    print {$client} "HTTP/1.1 $status $reason\r\n";
    print {$client} "Content-Type: application/json; charset=utf-8\r\n";
    print {$client} "Access-Control-Allow-Origin: *\r\n";
    print {$client} "Connection: close\r\n";
    print {$client} 'Content-Length: ' . length($body) . "\r\n\r\n";
    print {$client} $body;
}

sub trim {
    my ($value) = @_;
    $value = '' unless defined $value;
    $value =~ s/^\s+|\s+$//g;
    return $value;
}
