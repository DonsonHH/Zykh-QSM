#!/usr/bin/env perl
use strict;
use warnings;
use IO::Socket::INET;
use MIME::Base64 qw(encode_base64);

my $wav  = shift @ARGV || '';
my $host = $ENV{ASR_WS_HOST} || '127.0.0.1';
my $port = int($ENV{ASR_WS_PORT} || 6006);
my $stage = 'startup';

die "Usage: $0 input.wav\n" unless $wav ne '' && -s $wav;

sub read_exact {
    my ($fh, $count) = @_;
    my $data = '';
    while (length($data) < $count) {
        my $got = sysread($fh, my $part, $count - length($data));
        die "unexpected EOF during $stage\n" unless defined($got) && $got > 0;
        $data .= $part;
    }
    return $data;
}

sub read_wav {
    my ($path) = @_;
    open my $fh, '<:raw', $path or die "open $path: $!\n";
    my $head = read_exact($fh, 12);
    die "not a RIFF/WAVE file\n" unless substr($head, 0, 4) eq 'RIFF' && substr($head, 8, 4) eq 'WAVE';

    my ($format, $channels, $rate, $bits, $pcm);
    while (1) {
        my $got = sysread($fh, my $chunk_head, 8);
        last if defined($got) && $got == 0;
        die "truncated WAV chunk header\n" unless defined($got) && $got == 8;
        my ($name, $size) = unpack('a4V', $chunk_head);
        my $chunk = read_exact($fh, $size);
        read_exact($fh, 1) if $size & 1;
        if ($name eq 'fmt ') {
            ($format, $channels, $rate, undef, undef, $bits) = unpack('vvVVvv', $chunk);
        } elsif ($name eq 'data') {
            $pcm = $chunk;
        }
    }
    close $fh;

    die "missing WAV fmt/data chunk\n" unless defined($format) && defined($pcm);
    die "only mono PCM16 WAV is supported\n" unless $format == 1 && $channels == 1 && $bits == 16;
    my @samples = unpack('s<*', $pcm);
    my $floats = pack('f*', map { $_ / 32768.0 } @samples);
    return ($rate, scalar(@samples), $floats);
}

sub ws_send {
    my ($sock, $opcode, $payload) = @_;
    my $len = length($payload);
    my $mask = pack('N', int(rand(0xffffffff)));
    my $header;
    if ($len <= 125) {
        $header = pack('CC', 0x80 | $opcode, 0x80 | $len);
    } elsif ($len <= 65535) {
        $header = pack('CCn', 0x80 | $opcode, 0x80 | 126, $len);
    } else {
        $header = pack('CCNN', 0x80 | $opcode, 0x80 | 127, 0, $len);
    }
    my $mask_stream = substr($mask x (int($len / 4) + 1), 0, $len);
    my $frame = $header . $mask . ($payload ^ $mask_stream);
    my $offset = 0;
    while ($offset < length($frame)) {
        my $sent = syswrite($sock, $frame, length($frame) - $offset, $offset);
        die "websocket write failed: $!\n" unless defined($sent) && $sent > 0;
        $offset += $sent;
    }
}

sub ws_recv {
    my ($sock) = @_;
    while (1) {
        my ($first, $second) = unpack('CC', read_exact($sock, 2));
        my $opcode = $first & 0x0f;
        my $masked = $second & 0x80;
        my $len = $second & 0x7f;
        if ($len == 126) {
            $len = unpack('n', read_exact($sock, 2));
        } elsif ($len == 127) {
            my ($high, $low) = unpack('NN', read_exact($sock, 8));
            die "websocket frame is too large\n" if $high != 0;
            $len = $low;
        }
        my $mask = $masked ? read_exact($sock, 4) : '';
        my $payload = $len ? read_exact($sock, $len) : '';
        if ($masked) {
            my $stream = substr($mask x (int($len / 4) + 1), 0, $len);
            $payload ^= $stream;
        }
        if ($opcode == 9) {
            ws_send($sock, 10, $payload);
            next;
        }
        die "websocket closed by server\n" if $opcode == 8;
        return ($opcode, $payload) if $opcode == 1 || $opcode == 2;
    }
}

$stage = 'WAV parsing';
my ($sample_rate, $sample_count, $float_samples) = read_wav($wav);
my $sock = IO::Socket::INET->new(
    PeerHost => $host,
    PeerPort => $port,
    Proto    => 'tcp',
    Timeout  => int($ENV{ASR_WS_CONNECT_TIMEOUT} || 5),
) or die "connect ws://$host:$port failed: $!\n";
$sock->autoflush(1);

my $key = encode_base64(pack('N4', map { int(rand(0xffffffff)) } 1..4), '');
my $request = "GET / HTTP/1.1\r\n" .
              "Host: $host:$port\r\n" .
              "Upgrade: websocket\r\n" .
              "Connection: Upgrade\r\n" .
              "Sec-WebSocket-Key: $key\r\n" .
              "Sec-WebSocket-Version: 13\r\n\r\n";
print {$sock} $request;

$stage = 'WebSocket handshake';
my $response = '';
while ($response !~ /\r\n\r\n/s) {
    $response .= read_exact($sock, 1);
    die "oversized websocket handshake\n" if length($response) > 16384;
}
die "websocket handshake failed: $response\n" unless $response =~ m{^HTTP/1\.[01] 101\b};

$stage = 'audio upload';
my $payload = pack('V2', $sample_rate, $sample_count * 4) . $float_samples;
my $chunk_size = int($ENV{ASR_WS_CHUNK_BYTES} || 10240);
while (length($payload) > $chunk_size) {
    ws_send($sock, 2, substr($payload, 0, $chunk_size, ''));
}
ws_send($sock, 2, $payload) if length($payload);

$stage = 'recognition response';
my ($opcode, $result) = ws_recv($sock);
ws_send($sock, 1, 'Done');
close $sock;
print $result, "\n";
