#!/usr/bin/perl
use strict;
use warnings;
use Fcntl;
use Time::HiRes qw(time sleep);

# MAX30102 fixed script for QSM368ZP-WF
# Default:
#   I2C bus: /dev/i2c-3
#   I2C addr: 0x57
#   Samples: 150
#   Output JSON: /userdata/medical_assistant/data/vital_signs.json
#
# Usage:
#   perl /userdata/medical_assistant/scripts/read_max30102_vitals.pl
#   perl /userdata/medical_assistant/scripts/read_max30102_vitals.pl 200
#   perl /userdata/medical_assistant/scripts/read_max30102_vitals.pl 150 /userdata/medical_assistant/data/vital_signs.json

my $dev = '/dev/i2c-3';
my $addr = 0x57;
my $I2C_SLAVE = 0x0703;
my $target_samples = shift || 150;
my $json_path = shift || '/userdata/medical_assistant/data/vital_signs.json';
my $dt_sleep = 0.08;

sub json_str {
    my ($s) = @_;
    $s = '' unless defined $s;
    $s =~ s/\\/\\\\/g;
    $s =~ s/"/\\"/g;
    $s =~ s/\n/\\n/g;
    $s =~ s/\r/\\r/g;
    $s =~ s/\t/\\t/g;
    return '"' . $s . '"';
}

sub json_num {
    my ($v, $fmt) = @_;
    return 'null' unless defined $v;
    return sprintf($fmt || '%.1f', $v);
}

sub write_json {
    my (%d) = @_;

    my ($dir) = $json_path =~ m#^(.*)/[^/]+$#;
    system('mkdir', '-p', $dir) if defined $dir && length $dir;

    open(my $out, '>', $json_path) or die "open json output failed: $!\n";

    print $out "{\n";
    print $out "  \"sensor\": \"MAX30102\",\n";
    print $out "  \"source\": \"I2C3 /dev/i2c-3 addr 0x57\",\n";
    print $out "  \"timestamp_epoch\": " . time() . ",\n";
    print $out "  \"timestamp_local\": " . json_str(scalar localtime()) . ",\n";
    print $out "  \"max30102_connected\": " . ($d{connected} ? "true" : "false") . ",\n";
    print $out "  \"finger_detected\": " . ($d{finger_detected} ? "true" : "false") . ",\n";
    print $out "  \"heart_rate_bpm\": " . json_num($d{bpm}, '%.1f') . ",\n";
    print $out "  \"spo2_percent\": " . json_num($d{spo2}, '%.1f') . ",\n";
    print $out "  \"spo2_is_rough_estimate\": true,\n";
    print $out "  \"red_mean\": " . json_num($d{red_mean}, '%.1f') . ",\n";
    print $out "  \"red_std\": " . json_num($d{red_std}, '%.1f') . ",\n";
    print $out "  \"ir_mean\": " . json_num($d{ir_mean}, '%.1f') . ",\n";
    print $out "  \"ir_std\": " . json_num($d{ir_std}, '%.1f') . ",\n";
    print $out "  \"red_latest\": " . (defined $d{red_latest} ? int($d{red_latest}) : "null") . ",\n";
    print $out "  \"ir_latest\": " . (defined $d{ir_latest} ? int($d{ir_latest}) : "null") . ",\n";
    print $out "  \"sample_count\": " . (defined $d{sample_count} ? int($d{sample_count}) : 0) . ",\n";
    print $out "  \"target_samples\": " . int($target_samples) . ",\n";
    print $out "  \"peak_count\": " . (defined $d{peak_count} ? int($d{peak_count}) : 0) . ",\n";
    print $out "  \"valid_intervals\": " . (defined $d{valid_intervals} ? int($d{valid_intervals}) : 0) . ",\n";
    print $out "  \"ratio_R\": " . json_num($d{ratio_R}, '%.4f') . ",\n";
    print $out "  \"quality\": " . json_str($d{quality} || "unknown") . ",\n";
    print $out "  \"message\": " . json_str($d{message} || "") . "\n";
    print $out "}\n";

    close($out);
}

sub avg {
    my @x = @_;
    return 0 unless @x;
    my $s = 0;
    $s += $_ for @x;
    return $s / @x;
}

sub stddev {
    my @x = @_;
    return 0 unless @x > 1;
    my $m = avg(@x);
    my $s = 0;
    $s += ($_ - $m) * ($_ - $m) for @x;
    return sqrt($s / (@x - 1));
}

sub moving_avg {
    my ($arr, $win) = @_;
    my @out;
    my $n = scalar(@$arr);

    for my $i (0..$n-1) {
        my $a = $i - int($win / 2);
        my $b = $i + int($win / 2);
        $a = 0 if $a < 0;
        $b = $n - 1 if $b >= $n;
        push @out, avg(@$arr[$a..$b]);
    }

    return @out;
}

sub main {
    sysopen(my $fh, $dev, O_RDWR) or die "open $dev failed: $!\n";
    ioctl($fh, $I2C_SLAVE, $addr) or die "ioctl I2C_SLAVE failed: $!\n";

    sub wreg {
        my ($fh, $reg, $val) = @_;
        syswrite($fh, pack('CC', $reg, $val), 2) == 2
            or die sprintf("write reg 0x%02X failed\n", $reg);
    }

    sub rreg {
        my ($fh, $reg) = @_;
        syswrite($fh, pack('C', $reg), 1) == 1 or die "write addr failed\n";
        sysread($fh, my $buf, 1) == 1 or die "read reg failed\n";
        return unpack('C', $buf);
    }

    sub rbytes {
        my ($fh, $reg, $n) = @_;
        syswrite($fh, pack('C', $reg), 1) == 1 or die "write fifo addr failed\n";
        my $buf = '';
        my $got = sysread($fh, $buf, $n);
        die "read fifo failed, got " . (defined($got) ? $got : 'undef') . " bytes\n"
            unless defined($got) && $got == $n;
        return unpack('C*', $buf);
    }

    print "MAX30102 vitals init...\n";

    # Reset and configure.
    wreg($fh, 0x09, 0x40);
    sleep(0.5);

    # Clear FIFO.
    wreg($fh, 0x04, 0x00);
    wreg($fh, 0x05, 0x00);
    wreg($fh, 0x06, 0x00);

    # FIFO config, SpO2 config, LED currents.
    # This matches the tested working configuration on QSM368ZP-WF.
    wreg($fh, 0x08, 0x00);
    wreg($fh, 0x0A, 0x27);
    wreg($fh, 0x0C, 0x24);
    wreg($fh, 0x0D, 0x24);
    wreg($fh, 0x09, 0x03);

    sleep(0.8);

    my $part_id = rreg($fh, 0xFF);
    my $mode = rreg($fh, 0x09);
    my $fifo_cfg = rreg($fh, 0x08);
    my $spo2_cfg = rreg($fh, 0x0A);
    my $led1 = rreg($fh, 0x0C);
    my $led2 = rreg($fh, 0x0D);

    printf "PART_ID=0x%02X MODE=0x%02X FIFO_CFG=0x%02X SPO2_CFG=0x%02X LED1=0x%02X LED2=0x%02X\n",
        $part_id, $mode, $fifo_cfg, $spo2_cfg, $led1, $led2;

    die "unexpected MAX30102 PART_ID\n" unless $part_id == 0x15;

    print "Collecting $target_samples samples. Keep finger steady...\n";

    my (@t, @red, @ir);
    my $start = time();

    for my $i (1..$target_samples) {
        my @b = rbytes($fh, 0x07, 6);

        my $rv = ((($b[0] & 0x03) << 16) | ($b[1] << 8) | $b[2]);
        my $iv = ((($b[3] & 0x03) << 16) | ($b[4] << 8) | $b[5]);

        push @t, time() - $start;
        push @red, $rv;
        push @ir, $iv;

        if ($i <= 5 || $i % 25 == 0) {
            printf "sample=%03d RED=%6d IR=%6d WR=%02X OVF=%02X RD=%02X\n",
                $i, $rv, $iv, rreg($fh, 0x04), rreg($fh, 0x05), rreg($fh, 0x06);
        }

        sleep($dt_sleep);
    }

    my $n = scalar(@ir);
    my $red_latest = $red[-1];
    my $ir_latest = $ir[-1];

    # Drop startup settling samples.
    my $drop = $n > 80 ? 40 : 10;
    @t   = @t[$drop..$#t];
    @red = @red[$drop..$#red];
    @ir  = @ir[$drop..$#ir];

    my $ir_mean = avg(@ir);
    my $red_mean = avg(@red);
    my $ir_std = stddev(@ir);
    my $red_std = stddev(@red);

    my $finger_detected = ($ir_mean >= 20000) ? 1 : 0;

    my ($bpm, $spo2, $ratio_R);
    my $peak_count = 0;
    my $valid_intervals = 0;
    my $quality = "no_finger";
    my $message = "No finger detected or signal too weak.";

    if ($finger_detected) {
        my @smooth = moving_avg(\@ir, 5);
        my @base   = moving_avg(\@smooth, 35);
        my @sig;

        for my $i (0..$#smooth) {
            push @sig, $smooth[$i] - $base[$i];
        }

        my $sig_std = stddev(@sig);
        my $threshold = $sig_std * 0.35;
        $threshold = 15 if $threshold < 15;

        my @peaks;
        for my $i (2..$#sig-2) {
            next unless $sig[$i] > $sig[$i-1] && $sig[$i] >= $sig[$i+1];
            next unless $sig[$i] > $threshold;

            if (@peaks) {
                my $dt = $t[$i] - $t[$peaks[-1]];
                next if $dt < 0.35;
                next if $dt < 0.55 && $sig[$i] <= $sig[$peaks[-1]];
            }

            push @peaks, $i;
        }

        my @intervals;
        for my $i (1..$#peaks) {
            my $dt = $t[$peaks[$i]] - $t[$peaks[$i-1]];
            push @intervals, $dt if $dt >= 0.40 && $dt <= 1.60;
        }

        $peak_count = scalar(@peaks);
        $valid_intervals = scalar(@intervals);

        if (@intervals >= 2) {
            my $avg_dt = avg(@intervals);
            $bpm = 60.0 / $avg_dt;
        }

        my @red_smooth = moving_avg(\@red, 5);
        my @red_base   = moving_avg(\@red_smooth, 35);
        my @red_ac;
        my @ir_ac;

        for my $i (0..$#ir) {
            push @red_ac, $red_smooth[$i] - $red_base[$i];
            push @ir_ac,  $smooth[$i] - $base[$i];
        }

        my $red_ac_rms = stddev(@red_ac);
        my $ir_ac_rms  = stddev(@ir_ac);

        if ($red_mean > 0 && $ir_mean > 0 && $ir_ac_rms > 0) {
            $ratio_R = ($red_ac_rms / $red_mean) / ($ir_ac_rms / $ir_mean);
            $spo2 = 110.0 - 25.0 * $ratio_R;
            $spo2 = 100 if $spo2 > 100;
            $spo2 = 0 if $spo2 < 0;
        }

        if (defined $bpm && defined $spo2) {
            $quality = "ok";
            $message = "Measurement succeeded. SpO2 is a rough engineering estimate, not medical-grade calibration.";
        } else {
            $quality = "poor_signal";
            $message = "Finger detected, but pulse peaks were not clear enough. Keep finger steady and retry.";
        }
    }

    write_json(
        connected => 1,
        finger_detected => $finger_detected,
        bpm => $bpm,
        spo2 => $spo2,
        red_mean => $red_mean,
        red_std => $red_std,
        ir_mean => $ir_mean,
        ir_std => $ir_std,
        red_latest => $red_latest,
        ir_latest => $ir_latest,
        sample_count => $n,
        peak_count => $peak_count,
        valid_intervals => $valid_intervals,
        ratio_R => $ratio_R,
        quality => $quality,
        message => $message,
    );

    print "Collected samples: $n\n";
    printf "Signal summary: RED_mean=%.1f RED_std=%.1f IR_mean=%.1f IR_std=%.1f\n",
        $red_mean, $red_std, $ir_mean, $ir_std;
    print "finger_detected=" . ($finger_detected ? "true" : "false") . "\n";
    print "heart_rate_bpm=" . (defined $bpm ? sprintf("%.1f", $bpm) : "null") . "\n";
    print "spo2_percent=" . (defined $spo2 ? sprintf("%.1f", $spo2) : "null") . "\n";
    print "quality=$quality\n";
    print "json=$json_path\n";
}

my $ok = eval { main(); 1 };
if (!$ok) {
    my $err = $@ || "unknown error";
    chomp $err;
    write_json(
        connected => 0,
        finger_detected => 0,
        quality => "error",
        message => $err,
    );
    print "ERROR: $err\n";
    print "json=$json_path\n";
    exit 1;
}
