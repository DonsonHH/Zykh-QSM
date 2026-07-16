#!/usr/bin/env perl
use strict;
use warnings;
use Fcntl qw(O_RDWR O_NOCTTY O_NONBLOCK LOCK_EX);
use Time::HiRes qw(time sleep);

$| = 1;

my $device = $ENV{AS608_DEVICE} // '/dev/zykh-fingerprint';
my $command = shift(@ARGV) // 'status';

open(my $lock, '>', '/tmp/zykh-as608.lock')
    or die "cannot open fingerprint lock: $!\n";
flock($lock, LOCK_EX)
    or die "cannot lock fingerprint device: $!\n";

sub usage {
    die <<'USAGE';
Usage:
  as608.pl status
  as608.pl count
  as608.pl enroll ID [timeout_seconds]
  as608.pl identify [timeout_seconds]
  as608.pl delete ID
Environment: AS608_DEVICE=/dev/ttyUSBn
USAGE
}

my %confirmation_text = (
    0x00 => 'ok',
    0x01 => 'packet_receive_error',
    0x02 => 'no_finger',
    0x03 => 'image_enroll_failed',
    0x06 => 'image_too_messy',
    0x07 => 'too_few_features',
    0x08 => 'fingerprint_not_match',
    0x09 => 'no_match_found',
    0x0a => 'two_captures_not_match',
    0x0b => 'invalid_template_id',
    0x0c => 'flash_write_error',
    0x0d => 'invalid_template',
    0x0e => 'flash_load_error',
    0x0f => 'template_upload_error',
    0x10 => 'template_receive_error',
    0x11 => 'image_upload_error',
    0x12 => 'image_receive_error',
    0x13 => 'delete_error',
    0x15 => 'no_valid_image',
    0x18 => 'flash_error',
);

sub json_string {
    my ($value) = @_;
    $value =~ s/\\/\\\\/g;
    $value =~ s/"/\\"/g;
    $value =~ s/\r/\\r/g;
    $value =~ s/\n/\\n/g;
    return '"' . $value . '"';
}

sub result_json {
    my (%fields) = @_;
    my @parts;
    for my $key (sort keys %fields) {
        my $value = $fields{$key};
        my $encoded = !defined($value) ? 'null'
                    : $value =~ /\A-?\d+(?:\.\d+)?\z/ ? $value
                    : json_string($value);
        push @parts, json_string($key) . ':' . $encoded;
    }
    return '{' . join(',', @parts) . '}';
}

sub emit_event {
    my (%fields) = @_;
    print result_json(%fields), "\n";
}

sub fail_json {
    my ($message, $code) = @_;
    emit_event(ok => 0, error => $message,
               defined($code) ? (code => $code) : ());
    exit 1;
}

if (!-e $device && -x '/userdata/zykh_app/scripts/init_fingerprint.sh') {
    system('/userdata/zykh_app/scripts/init_fingerprint.sh', 'start');
}
fail_json("serial_device_not_found:$device") unless -e $device;

if (-x '/userdata/zykh_app/bin/ch340_init') {
    system('/userdata/zykh_app/bin/ch340_init', '-', '57600', '--quiet') == 0
        or fail_json('ch340_initialization_failed');
}
system('stty', '-F', $device, 'raw', '-echo') == 0
    or fail_json('tty_raw_mode_failed');

sysopen(my $port, $device, O_RDWR | O_NOCTTY | O_NONBLOCK)
    or fail_json("cannot_open_serial:$!");
binmode($port);

sub checksum16 {
    my ($bytes) = @_;
    my $sum = 0;
    $sum = ($sum + $_) & 0xffff for unpack('C*', $bytes);
    return $sum;
}

sub command_packet {
    my ($instruction, @params) = @_;
    my $payload = pack('C*', $instruction, @params);
    my $length = length($payload) + 2;
    my $body = pack('C n', 0x01, $length) . $payload;
    return pack('H*', 'ef01ffffffff') . $body . pack('n', checksum16($body));
}

sub drain_input {
    my $unused = '';
    while (1) {
        my $n = sysread($port, $unused, 512);
        last unless defined($n) && $n > 0;
    }
}

sub read_packet {
    my ($timeout) = @_;
    my $data = '';
    my $needed;
    my $deadline = time() + $timeout;
    while (time() < $deadline) {
        my $chunk = '';
        my $n = sysread($port, $chunk, 512);
        $data .= $chunk if defined($n) && $n > 0;
        my $header = index($data, pack('H*', 'ef01'));
        $data = substr($data, $header) if $header > 0;
        if (length($data) >= 9) {
            my @head = unpack('C*', substr($data, 0, 9));
            $needed = 9 + (($head[7] << 8) | $head[8]);
            last if length($data) >= $needed;
        }
        sleep(0.01);
    }
    return undef unless defined($needed) && length($data) >= $needed;
    $data = substr($data, 0, $needed);
    my @b = unpack('C*', $data);
    return undef unless $b[0] == 0xef && $b[1] == 0x01 && $b[6] == 0x07;
    my $payload_length = ($b[7] << 8) | $b[8];
    my $received = ($b[-2] << 8) | $b[-1];
    my $calculated = checksum16(substr($data, 6, 3 + $payload_length - 2));
    return undef unless $received == $calculated;
    return [ @b[9 .. $#b - 2] ];
}

sub transact {
    my ($instruction, @params) = @_;
    my $packet = command_packet($instruction, @params);
    for my $attempt (1 .. 3) {
        drain_input();
        my $written = syswrite($port, $packet);
        next unless defined($written) && $written == length($packet);
        my $payload = read_packet(0.8);
        return $payload if defined($payload);
        sleep(0.08);
    }
    fail_json(sprintf('module_timeout_command_0x%02x', $instruction));
}

sub confirmation_name {
    my ($code) = @_;
    return $confirmation_text{$code} // sprintf('unknown_0x%02x', $code);
}

sub wait_for_finger {
    my ($timeout) = @_;
    my $deadline = time() + $timeout;
    while (time() < $deadline) {
        my $reply = transact(0x01);
        return 1 if $reply->[0] == 0x00;
        if ($reply->[0] != 0x02 && $reply->[0] != 0x15) {
            fail_json('capture_' . confirmation_name($reply->[0]), $reply->[0]);
        }
        sleep(0.12);
    }
    fail_json('finger_wait_timeout');
}

sub wait_for_removal {
    my ($timeout) = @_;
    my $deadline = time() + $timeout;
    my $clear_samples = 0;
    while (time() < $deadline) {
        my $reply = transact(0x01);
        if ($reply->[0] == 0x02 || $reply->[0] == 0x15) {
            $clear_samples++;
            return 1 if $clear_samples >= 2;
        } else {
            $clear_samples = 0;
        }
        sleep(0.16);
    }
    fail_json('finger_removal_timeout');
}

sub image_to_buffer {
    my ($buffer_id) = @_;
    my $reply = transact(0x02, $buffer_id);
    fail_json('feature_' . confirmation_name($reply->[0]), $reply->[0])
        unless $reply->[0] == 0x00;
}

if ($command eq 'count') {
    my $reply = transact(0x1d);
    fail_json('count_' . confirmation_name($reply->[0]), $reply->[0])
        unless $reply->[0] == 0x00 && @$reply >= 3;
    my $count = ($reply->[1] << 8) | $reply->[2];
    emit_event(ok => 1, count => $count);
    exit 0;
}

if ($command eq 'status') {
    my $sys = transact(0x0f);
    fail_json('status_' . confirmation_name($sys->[0]), $sys->[0])
        unless $sys->[0] == 0x00 && @$sys >= 17;
    my $count_reply = transact(0x1d);
    fail_json('count_' . confirmation_name($count_reply->[0]), $count_reply->[0])
        unless $count_reply->[0] == 0x00 && @$count_reply >= 3;
    my $capacity = ($sys->[5] << 8) | $sys->[6];
    my $security = ($sys->[7] << 8) | $sys->[8];
    my $baud_factor = ($sys->[15] << 8) | $sys->[16];
    my $count = ($count_reply->[1] << 8) | $count_reply->[2];
    emit_event(ok => 1, model => 'AS608-compatible', count => $count,
               capacity => $capacity, security_level => $security,
               baud => 9600 * $baud_factor);
    exit 0;
}

if ($command eq 'enroll') {
    my $id = shift(@ARGV);
    usage() unless defined($id) && $id =~ /\A\d+\z/ && $id <= 299;
    my $timeout = shift(@ARGV) // 60;

    emit_event(ok => 1, event => 'place_finger_first', id => $id);
    wait_for_finger($timeout);
    image_to_buffer(1);
    emit_event(ok => 1, event => 'remove_finger', id => $id);
    wait_for_removal($timeout);
    emit_event(ok => 1, event => 'finger_removed', id => $id);
    emit_event(ok => 1, event => 'place_same_finger_second', id => $id);
    wait_for_finger($timeout);
    image_to_buffer(2);

    my $model = transact(0x05);
    fail_json('model_' . confirmation_name($model->[0]), $model->[0])
        unless $model->[0] == 0x00;
    my $store = transact(0x06, 1, ($id >> 8) & 0xff, $id & 0xff);
    fail_json('store_' . confirmation_name($store->[0]), $store->[0])
        unless $store->[0] == 0x00;
    emit_event(ok => 1, event => 'enrolled', id => $id);
    exit 0;
}

if ($command eq 'identify') {
    my $timeout = shift(@ARGV) // 45;
    emit_event(ok => 1, event => 'place_finger');
    wait_for_finger($timeout);
    image_to_buffer(1);
    my $reply = transact(0x04, 1, 0, 0, 0x01, 0x2c);
    if ($reply->[0] == 0x09) {
        emit_event(ok => 1, matched => 0);
        exit 2;
    }
    fail_json('search_' . confirmation_name($reply->[0]), $reply->[0])
        unless $reply->[0] == 0x00 && @$reply >= 5;
    my $id = ($reply->[1] << 8) | $reply->[2];
    my $score = ($reply->[3] << 8) | $reply->[4];
    emit_event(ok => 1, matched => 1, id => $id, score => $score);
    exit 0;
}

if ($command eq 'delete') {
    my $id = shift(@ARGV);
    usage() unless defined($id) && $id =~ /\A\d+\z/ && $id <= 299;
    my $reply = transact(0x0c, ($id >> 8) & 0xff, $id & 0xff, 0, 1);
    fail_json('delete_' . confirmation_name($reply->[0]), $reply->[0])
        unless $reply->[0] == 0x00;
    emit_event(ok => 1, deleted => $id);
    exit 0;
}

usage();
