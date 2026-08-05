#!/usr/bin/env perl

use strict;
use warnings;
use Fcntl qw(O_RDWR O_NOCTTY LOCK_EX LOCK_NB);
use JSON::PP qw(encode_json decode_json);
use POSIX qw(strftime tcflush TCIFLUSH);
use Time::HiRes qw(time);

my %options = (
    device            => $ENV{VITALS_UART_DEVICE} || '/dev/ttyS8',
    output            => $ENV{VITALS_UART_JSON} || '/userdata/zykh_app/data/vital_signs_uart8.json',
    timeout           => number_or($ENV{VITALS_UART_TIMEOUT_SECONDS}, 16),
    stable_frames     => int(number_or($ENV{VITALS_UART_STABLE_FRAMES}, 2)),
    reference_frames  => int(number_or($ENV{VITALS_UART_REFERENCE_FRAMES}, 2)),
    aggregate_samples => int(number_or($ENV{VITALS_UART_AGGREGATE_SAMPLES}, 5)),
    stabilization_grace => number_or($ENV{VITALS_UART_STABILIZATION_GRACE_SECONDS}, 12),
    spo2_grace        => number_or($ENV{VITALS_UART_SPO2_GRACE_SECONDS}, 8),
    minimum_measurement_seconds => number_or($ENV{VITALS_UART_MINIMUM_MEASUREMENT_SECONDS}, 4),
    minimum_contact_seconds => number_or($ENV{VITALS_UART_MINIMUM_CONTACT_SECONDS}, 2.6),
    chunk_size        => int(number_or($ENV{VITALS_UART_CHUNK_SIZE}, 128)),
    temperature_scale => number_or($ENV{VITALS_UART_TEMP_DECIMAL_SCALE}, 100),
    input_file        => '',
    state_file        => '',
    cancel_file       => '',
    session_id        => '',
    prewarmed         => 0,
);

parse_arguments(\%options, @ARGV);
$options{stable_frames} = 1 if $options{stable_frames} < 1;
$options{reference_frames} = 1 if $options{reference_frames} < 1;
$options{aggregate_samples} = 1 if $options{aggregate_samples} < 1;
$options{stabilization_grace} = 0 if $options{stabilization_grace} < 0;
$options{spo2_grace} = 0 if $options{spo2_grace} < 0;
$options{minimum_measurement_seconds} = 0 if $options{minimum_measurement_seconds} < 0;
$options{minimum_contact_seconds} = 0 if $options{minimum_contact_seconds} < 0;
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
if ($options{state_file} && !$options{input_file}) {
    my $status = $read_error && $read_error eq '__cancelled__'
        ? 'cancelled'
        : $payload->{ok}
            ? 'stabilizing'
            : 'failed';
    write_state(\%options, {
        ok               => $payload->{ok},
        status           => $status,
        hardware_started => JSON::PP::true,
        finger_detected  => $payload->{finger_detected} || JSON::PP::false,
        sample_count     => int($payload->{sample_count} || 0),
        valid_frame_count      => int($payload->{valid_frame_count} || 0),
        contact_frame_count    => int($payload->{contact_frame_count} || 0),
        heart_rate_frame_count => int($payload->{heart_rate_frame_count} || 0),
        spo2_frame_count       => int($payload->{spo2_frame_count} || 0),
        communication_status   => $payload->{communication_status} || 'no_protocol_frames',
        stable_core            => $payload->{stable_core} || JSON::PP::false,
        spo2_stabilization_extended => $payload->{spo2_stabilization_extended} || JSON::PP::false,
        error_message    => $payload->{error} || '',
    });
}
print encode_json($payload), "\n";
exit($payload->{ok} ? 0 : $read_error && $read_error eq '__cancelled__' ? 3 : 2);

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
        } elsif ($name eq '--stabilization-grace') {
            $options->{stabilization_grace} = number_or(require_value($name, \@args), $options->{stabilization_grace});
        } elsif ($name eq '--spo2-grace') {
            $options->{spo2_grace} = number_or(require_value($name, \@args), $options->{spo2_grace});
        } elsif ($name eq '--minimum-measurement-seconds') {
            $options->{minimum_measurement_seconds} = number_or(
                require_value($name, \@args),
                $options->{minimum_measurement_seconds},
            );
        } elsif ($name eq '--minimum-contact-seconds') {
            $options->{minimum_contact_seconds} = number_or(
                require_value($name, \@args),
                $options->{minimum_contact_seconds},
            );
        } elsif ($name eq '--chunk-size') {
            $options->{chunk_size} = int(number_or(require_value($name, \@args), $options->{chunk_size}));
        } elsif ($name eq '--temperature-scale') {
            $options->{temperature_scale} = number_or(require_value($name, \@args), 0);
        } elsif ($name eq '--input-file') {
            $options->{input_file} = require_value($name, \@args);
        } elsif ($name eq '--state-file') {
            $options->{state_file} = require_value($name, \@args);
        } elsif ($name eq '--cancel-file') {
            $options->{cancel_file} = require_value($name, \@args);
        } elsif ($name eq '--session-id') {
            $options->{session_id} = require_value($name, \@args);
        } elsif ($name eq '--prewarmed') {
            $options->{prewarmed} = 1;
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

    my $stopped = 0;
    my $stop_hardware = sub {
        return if $stopped;
        syswrite($uart, pack('C', 0x2A));
        $stopped = 1;
    };
    local $SIG{INT} = sub { $stop_hardware->(); close $uart; exit 130; };
    local $SIG{TERM} = sub { $stop_hardware->(); close $uart; exit 143; };

    if ($options->{prewarmed}) {
        # The algorithm is already running. Drop every frame produced before
        # the user pressed Start so only this measurement can become a result.
        tcflush(fileno($uart), TCIFLUSH);
    } else {
        # A final frame can arrive after the previous session's stop byte. Reset
        # the module before a cold start so stale vitals cannot seed a new run.
        syswrite($uart, pack('C', 0x2A));
        select(undef, undef, undef, 0.12);
        tcflush(fileno($uart), TCIFLUSH);
        my $written = syswrite($uart, pack('C', 0x24));
        if (!defined $written || $written != 1) {
            close $uart;
            return ([], "Failed to send start command to $device: $!");
        }
    }

    write_state($options, {
        ok               => JSON::PP::true,
        status           => 'starting',
        hardware_started => JSON::PP::true,
        finger_detected  => JSON::PP::false,
        sample_count     => 0,
        prewarmed         => $options->{prewarmed} ? JSON::PP::true : JSON::PP::false,
    });

    my $buffer = '';
    my @frames;
    my $started_at = time();
    my $deadline = $started_at + $options->{timeout};
    my $start_retried = 0;
    my $contact_window_set = 0;
    my $first_contact_at;
    my $stabilization_extended = 0;
    my $spo2_stabilization_extended = 0;
    while (time() < $deadline) {
        if ($options->{cancel_file} && -e $options->{cancel_file}) {
            $stop_hardware->();
            close $uart;
            return (\@frames, '__cancelled__');
        }
        my $count = sysread($uart, my $chunk, $options->{chunk_size});
        if (!defined $count) {
            next if $!{EINTR};
            $stop_hardware->();
            close $uart;
            return (\@frames, "Failed reading $device: $!");
        }
        if ($count > 0) {
            $buffer .= $chunk;
            extract_frames(\$buffer, \@frames);
            my @contact = grep { frame_has_contact($_) } @frames;
            my $contact_detected = contact_detected(\@frames);
            my @heart_rate = grep { $_->[2] > 0 } @frames;
            my @spo2 = grep { $_->[3] > 0 } @frames;
            $first_contact_at = time() if !defined($first_contact_at) && $contact_detected;
            if (!$contact_window_set && $contact_detected && $options->{stabilization_grace} > 0) {
                my $extended_deadline = time() + $options->{stabilization_grace};
                if ($extended_deadline > $deadline) {
                    $deadline = $extended_deadline;
                    $stabilization_extended = 1;
                }
                $contact_window_set = 1;
            }
            if (
                !$spo2_stabilization_extended
                && $options->{spo2_grace} > 0
                && time() >= $deadline - 0.25
                && @heart_rate >= $options->{stable_frames}
                && @spo2 < $options->{stable_frames}
            ) {
                $deadline = time() + $options->{spo2_grace};
                $spo2_stabilization_extended = 1;
                $options->{spo2_stabilization_extended} = 1;
            }
            write_state($options, {
                ok               => JSON::PP::true,
                status           => $contact_detected ? 'stabilizing' : 'waiting_finger',
                hardware_started => JSON::PP::true,
                finger_detected  => $contact_detected ? JSON::PP::true : JSON::PP::false,
                sample_count     => scalar(@frames),
                valid_frame_count      => scalar(@frames),
                contact_frame_count    => scalar(@contact),
                heart_rate_frame_count => scalar(@heart_rate),
                spo2_frame_count       => scalar(@spo2),
                communication_status   => 'receiving_protocol_frames',
                stabilization_extended => $stabilization_extended ? JSON::PP::true : JSON::PP::false,
                spo2_stabilization_extended => $spo2_stabilization_extended ? JSON::PP::true : JSON::PP::false,
                elapsed_seconds        => sprintf('%.2f', time() - $started_at) + 0,
            });
            my $measurement_old_enough = time() - $started_at >= $options->{minimum_measurement_seconds};
            my $contact_old_enough = defined($first_contact_at)
                && time() - $first_contact_at >= $options->{minimum_contact_seconds};
            last if measurement_window_ready(\@frames, $options)
                && $measurement_old_enough
                && $contact_old_enough;
        }
        if (!$options->{prewarmed} && !$start_retried && time() - $started_at >= 2) {
            # Any valid 24-byte frame proves the module is already running.
            # Restarting while SpO2 is stabilizing resets its measurement window.
            if (!@frames) {
                $stop_hardware->();
                select(undef, undef, undef, 0.08);
                syswrite($uart, pack('C', 0x24));
                $stopped = 0;
                $start_retried = 1;
                write_state($options, {
                    ok               => JSON::PP::true,
                    status           => 'waiting_finger',
                    hardware_started => JSON::PP::true,
                    finger_detected  => JSON::PP::false,
                    sample_count     => scalar(@frames),
                    start_retried    => JSON::PP::true,
                });
            }
        }
    }

    $stop_hardware->();
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

sub frame_has_contact {
    my ($frame) = @_;
    return $frame->[2] > 0 || $frame->[3] > 0;
}

sub contact_detected {
    my ($frames) = @_;
    return first_contact_frame($frames) > 0 ? 1 : 0;
}

sub first_contact_frame {
    my ($frames) = @_;
    my $consecutive_temperature = 0;
    for my $index (0 .. $#{$frames}) {
        my $frame = $frames->[$index];
        return $index + 1 if frame_has_contact($frame);
        if ($frame->[12] > 0) {
            $consecutive_temperature++;
            return $index + 1 if $consecutive_temperature >= 2;
        } else {
            $consecutive_temperature = 0;
        }
    }
    return 0;
}

sub measurement_window_ready {
    my ($frames, $options) = @_;
    my @recent = recent_signal_window($frames, $options);
    my @heart_rate = grep { $_->[2] > 0 } @recent;
    my @spo2 = grep { $_->[3] > 0 } @recent;
    # Blood pressure and HRV are optional reference fields. Waiting for them
    # kept an otherwise stable heart-rate/SpO2 result open until timeout.
    return @heart_rate >= $options->{stable_frames}
        && @spo2 >= $options->{stable_frames};
}

sub recent_signal_window {
    my ($frames, $options) = @_;
    my $window_size = $options->{stable_frames} * 2;
    $window_size = 4 if $window_size < 4;
    my $start = @{$frames} > $window_size ? @{$frames} - $window_size : 0;
    return @{$frames}[$start .. $#{$frames}] if @{$frames};
    return ();
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
            communication_status => 'no_protocol_frames',
            measured_at => now_text(),
        };
    }

    my @measured = grep { frame_has_measurement($_) } @{$frames};
    my @contact = grep { frame_has_contact($_) } @{$frames};
    my @heart_rate_frames = grep { $_->[2] > 0 } @{$frames};
    my @spo2_frames = grep { $_->[3] > 0 } @{$frames};
    my $stable_core = measurement_window_ready($frames, $options);
    my $latest = $frames->[-1];
    my $heart_rate = median_recent_nonzero($frames, 2, $options->{aggregate_samples});
    my $spo2 = median_recent_nonzero($frames, 3, $options->{aggregate_samples});
    my $core_complete = $heart_rate > 0 && $spo2 > 0;
    my $has_contact = contact_detected($frames);
    my $finger_detected = $has_contact ? JSON::PP::true : JSON::PP::false;
    my $quality = $stable_core
        ? 'stable'
        : $has_contact
            ? 'poor_signal'
            : 'no_finger';
    my $body_temperature = median_recent_temperature(
        $frames,
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
    my $systolic = median_recent_nonzero($frames, 5, $options->{aggregate_samples});
    my $diastolic = median_recent_nonzero($frames, 6, $options->{aggregate_samples});
    my $hrv_sdnn = median_recent_nonzero($frames, 10, $options->{aggregate_samples});
    my $hrv_rmssd = median_recent_nonzero($frames, 11, $options->{aggregate_samples});
    my $reference_ready = $systolic > 0 && $diastolic > 0 && ($hrv_sdnn > 0 || $hrv_rmssd > 0);

    return {
        ok                      => $core_complete ? JSON::PP::true : JSON::PP::false,
        status                  => $core_complete ? 'measured' : $has_contact ? 'stabilizing' : 'awaiting_finger',
        source                  => 'UART8-vitals-24B',
        device                  => $options->{device},
        heart_rate_bpm          => $heart_rate,
        spo2_percent            => $spo2,
        microcirculation        => median_recent_nonzero($frames, 4, $options->{aggregate_samples}),
        systolic_pressure       => $systolic,
        diastolic_pressure      => $diastolic,
        respiratory_rate        => median_recent_nonzero($frames, 7, $options->{aggregate_samples}),
        fatigue                 => median_recent_nonzero($frames, 8, $options->{aggregate_samples}),
        rr_interval             => median_recent_nonzero($frames, 9, $options->{aggregate_samples}),
        hrv_sdnn                => $hrv_sdnn,
        hrv_rmssd               => $hrv_rmssd,
        body_temperature_raw    => $body_temperature->{raw},
        ambient_temperature_raw => $ambient_temperature->{raw},
        body_temperature_c      => $body_temperature->{value},
        ambient_temperature_c   => $ambient_temperature->{value},
        temperature_scale       => $options->{temperature_scale} || undef,
        reference_ready         => $reference_ready ? JSON::PP::true : JSON::PP::false,
        stable_core             => $stable_core ? JSON::PP::true : JSON::PP::false,
        communication_status    => 'receiving_protocol_frames',
        spo2_stabilization_extended => $options->{spo2_stabilization_extended}
            ? JSON::PP::true
            : JSON::PP::false,
        finger_detected         => $finger_detected,
        quality                 => $quality,
        message                 => $core_complete
            ? 'Integrated UART vitals measurement received'
            : $has_contact
                ? 'Finger detected; waiting for heart-rate and SpO2 to stabilize'
            : 'No finger measurement yet; keep the fingertip steady and retry',
        sample_count            => scalar(@{$frames}),
        valid_frame_count       => scalar(@{$frames}),
        measured_frame_count    => scalar(@measured),
        contact_frame_count     => scalar(@contact),
        heart_rate_frame_count  => scalar(@heart_rate_frames),
        spo2_frame_count        => scalar(@spo2_frames),
        first_contact_frame     => first_contact_frame($frames) || undef,
        first_heart_rate_frame  => first_matching_frame($frames, sub { $_[0]->[2] > 0 }),
        first_spo2_frame        => first_matching_frame($frames, sub { $_[0]->[3] > 0 }),
        signal_trace            => signal_trace($frames, 12),
        raw_frame_hex           => join(' ', map { sprintf('%02X', $_) } @{$latest}),
        read_error              => $read_error || undef,
        measured_at             => now_text(),
    };
}

sub first_matching_frame {
    my ($frames, $predicate) = @_;
    for my $index (0 .. $#{$frames}) {
        return $index + 1 if $predicate->($frames->[$index]);
    }
    return undef;
}

sub signal_trace {
    my ($frames, $limit) = @_;
    $limit = 12 unless defined $limit && $limit > 0;
    my $start = @{$frames} > $limit ? @{$frames} - $limit : 0;
    my @trace;
    for my $index ($start .. $#{$frames}) {
        my $frame = $frames->[$index];
        push @trace, {
            frame      => $index + 1,
            heart_rate => $frame->[2] + 0,
            spo2       => $frame->[3] + 0,
            respiration => $frame->[7] + 0,
            hrv_sdnn   => $frame->[10] + 0,
            hrv_rmssd  => $frame->[11] + 0,
            finger_temperature_integer => $frame->[12] + 0,
            finger_temperature_decimal => $frame->[13] + 0,
        };
    }
    return \@trace;
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

sub write_state {
    my ($options, $changes) = @_;
    return unless $options->{state_file};
    my $existing = read_json_file($options->{state_file});
    my $state = {
        %{$existing || {}},
        session_id => $options->{session_id} || '',
        source     => 'UART8-vitals-24B',
        updated_at => now_text(),
        %{$changes || {}},
    };
    my $temporary = "$options->{state_file}.$$";
    write_json($temporary, $state);
    rename $temporary, $options->{state_file};
}

sub read_json_file {
    my ($path) = @_;
    return {} unless $path && -s $path;
    open my $fh, '<:raw', $path or return {};
    local $/;
    my $raw = <$fh>;
    close $fh;
    my $payload = eval { decode_json($raw || '') };
    return $payload && ref($payload) eq 'HASH' ? $payload : {};
}

sub now_text {
    return strftime('%Y-%m-%dT%H:%M:%S%z', localtime);
}
