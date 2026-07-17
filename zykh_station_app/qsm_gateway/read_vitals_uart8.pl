#!/usr/bin/env perl

use strict;
use warnings;
use Fcntl qw(O_RDWR O_NOCTTY LOCK_EX LOCK_NB);
use JSON::PP qw(encode_json);
use POSIX qw(strftime);
use Time::HiRes qw(time);

my %options = (
    device            => $ENV{VITALS_UART_DEVICE} || '/dev/ttyS8',
    output            => $ENV{VITALS_UART_JSON} || '/userdata/zykh_app/data/vital_signs_uart8.json',
    timeout           => number_or($ENV{VITALS_UART_TIMEOUT_SECONDS}, 16),
    stable_frames     => int(number_or($ENV{VITALS_UART_STABLE_FRAMES}, 3)),
    reference_frames  => int(number_or($ENV{VITALS_UART_REFERENCE_FRAMES}, 2)),
    aggregate_samples => int(number_or($ENV{VITALS_UART_AGGREGATE_SAMPLES}, 5)),
    chunk_size        => int(number_or($ENV{VITALS_UART_CHUNK_SIZE}, 128)),
    temperature_scale => number_or($ENV{VITALS_UART_TEMP_DECIMAL_SCALE}, 100),
    input_file        => '',
);

parse_arguments(\%options, @ARGV);
$options{stable_frames} = 1 if $options{stable_frames} < 1;
$options{reference_frames} = 1 if $options{reference_frames} < 1;
$options{aggregate_samples} = 1 if $options{aggregate_samples} < 1;
$options{chunk_size} = 1 if $options{chunk_size} < 1;
$options{timeout} = 1 if $options{timeout} < 1;

my $lock_path = $ENV{VITALS_UART_LOCK_FILE} || '/tmp/zykh-vitals-uart8.lock';
open my $lock_fh, '>>', $lock_path or die "Cannot open UART lock $lock_path: $!\n";
if (!flock($lock_fh, LOCK_EX | LOCK_NB)) {
    my $busy = {
        ok          => JSON::PP::false,
        status      => 'busy',
        source      => 'UART8-vitals-24B',
        device      => $options{device},
        error       => 'A vitals measurement is already in progress',
        measured_at => now_text(),
    };
    write_json($options{output}, $busy);
    print encode_json($busy), "\n";
    exit 2;
}

my ($frames, $read_error);
if ($options{input_file}) {
    ($frames, $read_error) = read_fixture_frames(\%options);
} else {
    ($frames, $read_error) = read_uart_frames(\%options);
}

my $payload = build_payload($frames, $read_error, \%options);
write_json($options{output}, $payload);
print encode_json($payload), "\n";
exit($payload->{ok} ? 0 : 2);

sub parse_arguments {
    my ($options, @args) = @_;

    # Compatibility with the existing QSM gateway invocation:
    # perl read_vitals_uart8.pl <legacy_sample_count> <output.json>
    if (@args && $args[0] =~ /^\d+$/) {
        shift @args;
        $options->{output} = shift @args if @args && $args[0] !~ /^--/;
    }

    while (@args) {
        my $name = shift @args;
        if ($name eq '--device') {
            $options->{device} = require_value($name, \@args);
        } elsif ($name eq '--output') {
            $options->{output} = require_value($name, \@args);
        } elsif ($name eq '--timeout') {
            $options->{timeout} = number_or(require_value($name, \@args), $options->{timeout});
        } elsif ($name eq '--stable-frames') {
            $options->{stable_frames} = int(number_or(require_value($name, \@args), $options->{stable_frames}));
        } elsif ($name eq '--reference-frames') {
            $options->{reference_frames} = int(number_or(require_value($name, \@args), $options->{reference_frames}));
        } elsif ($name eq '--aggregate-samples') {
            $options->{aggregate_samples} = int(number_or(require_value($name, \@args), $options->{aggregate_samples}));
        } elsif ($name eq '--chunk-size') {
            $options->{chunk_size} = int(number_or(require_value($name, \@args), $options->{chunk_size}));
        } elsif ($name eq '--temperature-scale') {
            $options->{temperature_scale} = number_or(require_value($name, \@args), 0);
        } elsif ($name eq '--input-file') {
            $options->{input_file} = require_value($name, \@args);
        } else {
            die "Unknown argument: $name\n";
        }
    }
}

sub require_value {
    my ($name, $args) = @_;
    die "$name requires a value\n" unless @{$args};
    return shift @{$args};
}

sub number_or {
    my ($value, $fallback) = @_;
    return $fallback unless defined $value && $value =~ /^\d+(?:\.\d+)?$/;
    return $value + 0;
}

sub read_fixture_frames {
    my ($options) = @_;
    open my $fh, '<:raw', $options->{input_file}
        or return ([], "Cannot open fixture $options->{input_file}: $!");
    my $buffer = '';
    my @frames;
    while (1) {
        my $count = read($fh, my $chunk, $options->{chunk_size});
        if (!defined $count) {
            close $fh;
            return (\@frames, "Cannot read fixture: $!");
        }
        last if $count == 0;
        $buffer .= $chunk;
        extract_frames(\$buffer, \@frames);
        last if measurement_window_ready(\@frames, $options);
    }
    close $fh;
    return (\@frames, '');
}

sub read_uart_frames {
    my ($options) = @_;
    my $device = $options->{device};
    return ([], "UART device does not exist: $device") unless -e $device;

    my @stty = (
        'stty', '-F', $device, '9600', 'cs8', '-cstopb', '-parenb',
        '-ixon', '-ixoff', '-crtscts', 'raw', '-echo', 'min', '0', 'time', '10',
    );
    system(@stty) == 0
        or return ([], "Failed to configure $device for 9600 8N1");

    sysopen(my $uart, $device, O_RDWR | O_NOCTTY)
        or return ([], "Cannot open $device: $!");
    binmode($uart);

    my $written = syswrite($uart, pack('C', 0x24));
    if (!defined $written || $written != 1) {
        close $uart;
        return ([], "Failed to send start command to $device: $!");
    }

    my $buffer = '';
    my @frames;
    my $deadline = time() + $options->{timeout};
    while (time() < $deadline) {
        my $count = sysread($uart, my $chunk, $options->{chunk_size});
        if (!defined $count) {
            next if $!{EINTR};
            syswrite($uart, pack('C', 0x2A));
            close $uart;
            return (\@frames, "Failed reading $device: $!");
        }
        if ($count > 0) {
            $buffer .= $chunk;
            extract_frames(\$buffer, \@frames);
            last if measurement_window_ready(\@frames, $options);
        }
    }

    syswrite($uart, pack('C', 0x2A));
    close $uart;
    return (\@frames, '');
}

sub extract_frames {
    my ($buffer_ref, $frames) = @_;
    while (length($$buffer_ref) >= 24) {
        my $header = index($$buffer_ref, "\xFF");
        if ($header < 0) {
            $$buffer_ref = '';
            return;
        }
        substr($$buffer_ref, 0, $header, '') if $header > 0;
        return if length($$buffer_ref) < 24;

        my $candidate = substr($$buffer_ref, 0, 24);
        my @bytes = unpack('C*', $candidate);
        if ($bytes[0] == 0xFF && $bytes[1] == 0x01 && $bytes[23] == 0xF1) {
            substr($$buffer_ref, 0, 24, '');
            push @{$frames}, \@bytes;
            next;
        }
        substr($$buffer_ref, 0, 1, '');
    }
}

sub frame_has_measurement {
    my ($frame) = @_;
    return $frame->[2] > 0 && $frame->[3] > 0;
}

sub measurement_window_ready {
    my ($frames, $options) = @_;
    my @measured = grep { frame_has_measurement($_) } @{$frames};
    # Blood pressure and HRV are optional reference fields. Waiting for them
    # kept an otherwise stable heart-rate/SpO2 result open until timeout.
    return @measured >= $options->{stable_frames};
}

sub build_payload {
    my ($frames, $read_error, $options) = @_;
    if (!@{$frames}) {
        return {
            ok          => JSON::PP::false,
            status      => 'unavailable',
            source      => 'UART8-vitals-24B',
            device      => $options->{device},
            error       => $read_error || 'No valid 24-byte frame received',
            measured_at => now_text(),
        };
    }

    my @measured = grep { frame_has_measurement($_) } @{$frames};
    my @signal_frames = @measured ? @measured : @{$frames};
    my $latest = $signal_frames[-1];
    my $finger_detected = @measured ? JSON::PP::true : JSON::PP::false;
    my $quality = @measured >= $options->{stable_frames}
        ? 'stable'
        : @measured
            ? 'poor_signal'
            : 'no_finger';
    my $body_temperature = median_recent_temperature(
        \@signal_frames,
        12,
        13,
        $options->{temperature_scale},
        $options->{aggregate_samples},
    );
    my $ambient_temperature = median_recent_temperature(
        $frames,
        14,
        15,
        $options->{temperature_scale},
        $options->{aggregate_samples},
    );
    my $systolic = median_recent_nonzero(\@signal_frames, 5, $options->{aggregate_samples});
    my $diastolic = median_recent_nonzero(\@signal_frames, 6, $options->{aggregate_samples});
    my $hrv_sdnn = median_recent_nonzero(\@signal_frames, 10, $options->{aggregate_samples});
    my $hrv_rmssd = median_recent_nonzero(\@signal_frames, 11, $options->{aggregate_samples});
    my $reference_ready = $systolic > 0 && $diastolic > 0 && ($hrv_sdnn > 0 || $hrv_rmssd > 0);

    return {
        ok                      => JSON::PP::true,
        status                  => @measured ? 'measured' : 'awaiting_finger',
        source                  => 'UART8-vitals-24B',
        device                  => $options->{device},
        heart_rate_bpm          => median_recent_nonzero(\@signal_frames, 2, $options->{aggregate_samples}),
        spo2_percent            => median_recent_nonzero(\@signal_frames, 3, $options->{aggregate_samples}),
        microcirculation        => median_recent_nonzero(\@signal_frames, 4, $options->{aggregate_samples}),
        systolic_pressure       => $systolic,
        diastolic_pressure      => $diastolic,
        respiratory_rate        => median_recent_nonzero(\@signal_frames, 7, $options->{aggregate_samples}),
        fatigue                 => median_recent_nonzero(\@signal_frames, 8, $options->{aggregate_samples}),
        rr_interval             => median_recent_nonzero(\@signal_frames, 9, $options->{aggregate_samples}),
        hrv_sdnn                => $hrv_sdnn,
        hrv_rmssd               => $hrv_rmssd,
        body_temperature_raw    => $body_temperature->{raw},
        ambient_temperature_raw => $ambient_temperature->{raw},
        body_temperature_c      => $body_temperature->{value},
        ambient_temperature_c   => $ambient_temperature->{value},
        temperature_scale       => $options->{temperature_scale} || undef,
        reference_ready         => $reference_ready ? JSON::PP::true : JSON::PP::false,
        finger_detected         => $finger_detected,
        quality                 => $quality,
        message                 => @measured
            ? 'Integrated UART vitals measurement received'
            : 'No finger measurement yet; keep the fingertip steady and retry',
        sample_count            => scalar(@{$frames}),
        valid_frame_count       => scalar(@{$frames}),
        measured_frame_count    => scalar(@measured),
        raw_frame_hex           => join(' ', map { sprintf('%02X', $_) } @{$latest}),
        read_error              => $read_error || undef,
        measured_at             => now_text(),
    };
}

sub median {
    my ($frames, $index) = @_;
    my @values = sort { $a <=> $b } map { $_->[$index] + 0 } @{$frames};
    return 0 unless @values;
    return $values[int(@values / 2)];
}

sub median_recent_nonzero {
    my ($frames, $index, $limit) = @_;
    my @values;
    for my $frame (reverse @{$frames}) {
        my $value = $frame->[$index] + 0;
        next unless $value > 0;
        push @values, $value;
        last if @values >= $limit;
    }
    @values = sort { $a <=> $b } @values;
    return 0 unless @values;
    return $values[int(@values / 2)];
}

sub median_recent_temperature {
    my ($frames, $integer_index, $decimal_index, $scale, $limit) = @_;
    my @samples;
    for my $frame (reverse @{$frames}) {
        my $integer = $frame->[$integer_index] + 0;
        next unless $integer > 0;
        my $decimal = $frame->[$decimal_index] + 0;
        my $value = $scale > 0 ? $integer + ($decimal / $scale) : undef;
        push @samples, { integer => $integer, decimal => $decimal, value => $value };
        last if @samples >= $limit;
    }
    return { raw => { integer => 0, decimal => 0 }, value => undef } unless @samples;
    @samples = sort {
        (($a->{value} // $a->{integer}) <=> ($b->{value} // $b->{integer}))
    } @samples;
    my $median = $samples[int(@samples / 2)];
    return {
        raw => { integer => $median->{integer}, decimal => $median->{decimal} },
        value => defined $median->{value} ? sprintf('%.2f', $median->{value}) + 0 : undef,
    };
}

sub write_json {
    my ($path, $payload) = @_;
    my $slash = rindex($path, '/');
    my $directory = $slash > 0 ? substr($path, 0, $slash) : $slash == 0 ? '/' : '';
    if ($directory && !-d $directory) {
        system('mkdir', '-p', $directory) == 0
            or die "Cannot create output directory $directory\n";
    }
    open my $fh, '>:raw', $path or die "Cannot write $path: $!\n";
    print {$fh} encode_json($payload);
    close $fh;
}

sub now_text {
    return strftime('%Y-%m-%dT%H:%M:%S%z', localtime);
}
