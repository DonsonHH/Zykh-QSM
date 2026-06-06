#!/usr/bin/perl
use strict;
use warnings;
use Time::HiRes qw(time);

my $dev = shift || "/dev/ttyS4";
my $out = shift || "/userdata/medical_assistant/data/gy614_temp.json";

system("stty -F $dev 9600 cs8 -cstopb -parenb -ixon -ixoff -crtscts clocal raw -echo");

open(my $fh, "<", $dev) or die "open $dev failed: $!\n";
binmode($fh);

my $deadline = time() + 10;
my $best;

while (time() < $deadline) {
    my $c = "";
    my $n = sysread($fh, $c, 1);
    next unless $n;
    next unless ord($c) == 0xA4;

    my $rest = "";
    while (length($rest) < 11 && time() < $deadline) {
        my $r = "";
        my $m = sysread($fh, $r, 11 - length($rest));
        $rest .= $r if $m;
    }

    next unless length($rest) == 11;

    my $frame = $c . $rest;
    my @b = unpack("C*", $frame);

    my $sum = 0;
    for my $i (0..10) {
        $sum = ($sum + $b[$i]) & 0xff;
    }
    next unless $sum == $b[11];

    my $to = (($b[5] << 8) | $b[6]) / 100.0;
    my $ta = (($b[7] << 8) | $b[8]) / 100.0;
    my $bo = (($b[9] << 8) | $b[10]) / 100.0;

    next if $ta < -20 || $ta > 80;
    next if $bo < 20 || $bo > 45;

    my $raw = uc(unpack("H*", $frame));

    $best = {
        to => $to,
        ta => $ta,
        bo => $bo,
        emissivity => $b[4],
        raw => $raw
    };
    last;
}

die "no valid GY-614 frame from $dev\n" unless $best;

my ($dir) = $out =~ m#^(.*)/[^/]+$#;
system("mkdir", "-p", $dir) if defined $dir && length $dir;

open(my $ofh, ">", $out) or die "write $out failed: $!\n";
print $ofh "{\n";
print $ofh "  \"sensor\": \"GY-614\",\n";
print $ofh "  \"uart\": \"$dev\",\n";
print $ofh "  \"connected\": true,\n";
print $ofh "  \"target_temp_c\": " . $best->{to} . ",\n";
print $ofh "  \"ambient_temp_c\": " . $best->{ta} . ",\n";
print $ofh "  \"body_temp_c\": " . $best->{bo} . ",\n";
print $ofh "  \"emissivity_percent\": " . $best->{emissivity} . ",\n";
print $ofh "  \"raw_hex\": \"" . $best->{raw} . "\"\n";
print $ofh "}\n";
close($ofh);

system("cat", $out);
