#!/usr/bin/env perl

use strict;
use warnings;
use File::Copy qw(copy);

my $target = $ARGV[0] || '/userdata/zykh_app/server.pl';
my $backup = "$target.before-empty-request-exit";

open my $input, '<:raw', $target or die "Cannot read $target: $!\n";
local $/;
my $source = <$input>;
close $input;

my $changed = 0;

if ($source !~ /ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT/) {
    my $pattern = qr{
        if\s*\(\s*!\$req\s*\)\s*\{\s*
        close\s+\$client\s*;\s*
        next\s*;\s*
        \}
    }x;
    my $replacement = <<'PERL';
if (!$req) {
            close $client;
            # ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT
            exit 0;
        }
PERL
    my $matches = () = $source =~ /$pattern/g;
    die "Expected exactly one empty-request child block, found $matches\n" unless $matches == 1;
    $source =~ s/$pattern/$replacement/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT/) {
    my $before = <<'PERL';
    my $last_path = '';
    my $last_mtime = 0;
    my $delay = 1 / $fps;
    while (1) {
        my $path = latest_stream_frame();
        if ($path && -s $path) {
            my $mtime = (stat($path))[9] || 0;
            if ($path ne $last_path || $mtime != $last_mtime) {
                open my $fh, '<:raw', $path or last;
                local $/;
                my $jpg = <$fh>;
                close $fh;
                if ($jpg && length($jpg) > 1000) {
                    my $head = "--$boundary\r\nContent-Type: image/jpeg\r\nContent-Length: " . length($jpg) . "\r\n\r\n";
                    last unless print {$client} $head;
                    last unless print {$client} $jpg;
                    last unless print {$client} "\r\n";
                    $last_path = $path;
                    $last_mtime = $mtime;
                }
            }
        }
        select(undef, undef, undef, $delay);
    }
PERL
    my $after = <<'PERL';
    my $last_path = '';
    my $last_mtime = 0;
    my $idle_ticks = 0;
    my $delay = 1 / $fps;
    while (1) {
        my $sent_frame = 0;
        my $path = latest_stream_frame();
        if ($path && -s $path) {
            my $mtime = (stat($path))[9] || 0;
            if ($path ne $last_path || $mtime != $last_mtime) {
                open my $fh, '<:raw', $path or last;
                local $/;
                my $jpg = <$fh>;
                close $fh;
                if ($jpg && length($jpg) > 1000) {
                    my $head = "--$boundary\r\nContent-Type: image/jpeg\r\nContent-Length: " . length($jpg) . "\r\n\r\n";
                    last unless print {$client} $head;
                    last unless print {$client} $jpg;
                    last unless print {$client} "\r\n";
                    $last_path = $path;
                    $last_mtime = $mtime;
                    $sent_frame = 1;
                }
            }
        }
        # ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT
        $idle_ticks = $sent_frame ? 0 : $idle_ticks + 1;
        last if $idle_ticks >= $fps * 3;
        select(undef, undef, undef, $delay);
    }
PERL
    my $matches = () = $source =~ /\Q$before\E/g;
    die "Expected exactly one MJPEG stream loop, found $matches\n" unless $matches == 1;
    $source =~ s/\Q$before\E/$after/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_AUDIO_STOP_ALL/) {
    my $pattern = qr{
        if\s*\(\s*\$method\s+eq\s+'POST'\s*&&\s*\$path\s+eq\s+'/api/audio/stream/stop'\s*\)\s*\{\s*
        return\s+send_json\(\$client,\s*200,\s*stop_audio_pcm_stream\(\)\);\s*
        \}
    }x;
    my $replacement = <<'PERL';
if ($method eq 'POST' && $path eq '/api/audio/stream/stop') {
        # ZYKH_STATION_AUDIO_STOP_ALL
        return send_json($client, 200, release_audio_playback_device());
    }
PERL
    my $matches = () = $source =~ /$pattern/g;
    die "Expected exactly one audio stream stop route, found $matches\n" unless $matches == 1;
    $source =~ s/$pattern/$replacement/;
    $changed = 1;
}

if (!$changed) {
    print "Station gateway reliability fixes already installed.\n";
    exit 0;
}

my $temporary = "$target.station-patch.$$";
open my $output, '>:raw', $temporary or die "Cannot write $temporary: $!\n";
print {$output} $source;
close $output;

system('perl', '-c', $temporary) == 0 or do {
    unlink $temporary;
    die "Patched station gateway did not compile\n";
};

copy($target, $backup) or die "Cannot create $backup: $!\n" unless -f $backup;
rename $temporary, $target or die "Cannot replace $target: $!\n";
chmod 0755, $target;
print "Installed station gateway reliability fixes.\n";
