from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


PATCHER = Path(__file__).resolve().parents[1] / "patch_station_gateway.pl"


class StationGatewayPatchTest(unittest.TestCase):
    def test_empty_request_exits_child_instead_of_reentering_accept_loop(self) -> None:
        source = """#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP ();
use POSIX ();
my $req;
my $client;
if (!$req) {
    close $client;
    next;
}
my $fps = 30;
my $boundary = "frame";
my $method = "POST";
my $path = "/api/audio/stream/stop";
my $DATA_DIR = "/tmp";
if ($method eq 'POST' && $path eq '/api/audio/stream/stop') {
    return send_json($client, 200, stop_audio_pcm_stream());
}
if ($method eq 'POST' && $path eq '/api/audio/speak') {
    return send_json($client, 200, speak_text($req->{params}));
}
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
                    my $head = "--$boundary\\r\\nContent-Type: image/jpeg\\r\\nContent-Length: " . length($jpg) . "\\r\\n\\r\\n";
                    last unless print {$client} $head;
                    last unless print {$client} $jpg;
                    last unless print {$client} "\\r\\n";
                    $last_path = $path;
                    $last_mtime = $mtime;
                }
            }
        }
        select(undef, undef, undef, $delay);
    }
sub latest_stream_frame { return ""; }
sub run_tts_command {
    my ($cmd, $log, $timeout) = @_;
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($timeout || 90), 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        exit_code => $exit,
        detail => substr(read_text_file($log) || '', 0, 500),
    };
}
sub exercise_tts_attempts {
    my ($attempt, $log) = @_;
    my $requested_mode = 'offline';
        my $run = run_tts_command($attempt->{command}, $log, $attempt->{timeout});
        if ($run->{ok}) {
            return { ok => JSON::PP::true };
        }
    return { ok => JSON::PP::false };
}
sub release_audio_playback_device {
    stop_audio_pcm_stream();
    system('sh', '-c', 'killall aplay 2>/dev/null');
    select(undef, undef, undef, 0.18);
    return { ok => JSON::PP::true };
}
sub stop_audio_pcm_stream { return { ok => JSON::PP::true }; }
sub shell_quote { return "''"; }
sub read_text_file { return ''; }
sub read_file_trim { return ''; }
sub write_text_file { return; }
"""
        with tempfile.TemporaryDirectory() as directory:
            gateway = Path(directory) / "server.pl"
            gateway.write_text(source, encoding="utf-8")

            subprocess.run(["perl", str(PATCHER), str(gateway)], check=True, capture_output=True, text=True)
            patched = gateway.read_text(encoding="utf-8")
            subprocess.run(["perl", str(PATCHER), str(gateway)], check=True, capture_output=True, text=True)

        self.assertIn("ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT", patched)
        self.assertIn("exit 0;", patched)
        self.assertNotIn("close $client;\n    next;", patched)
        self.assertIn("ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT", patched)
        self.assertIn("$idle_ticks >= $fps * 3", patched)
        self.assertIn("ZYKH_STATION_AUDIO_STOP_ALL", patched)
        self.assertIn("ZYKH_STATION_AUDIO_STOP_ALL_V2", patched)
        self.assertIn("release_audio_playback_device()", patched)
        self.assertIn("ZYKH_STATION_QSM_TTS", patched)
        self.assertNotIn("host-offline-tts-required", patched)
        self.assertIn("speak_text($req->{params})", patched)
        self.assertIn("ZYKH_STATION_TTS_PROCESS_GROUP", patched)
        self.assertIn("POSIX::setpgid", patched)
        self.assertIn('audio-tts.pid', patched)
        self.assertIn("ZYKH_STATION_TTS_CANCEL_HELPER", patched)
        self.assertIn("kill 'TERM', -int($pid)", patched)
        self.assertIn("ZYKH_STATION_RELEASE_CANCELS_TTS", patched)
        self.assertIn("ZYKH_STATION_TTS_CANCEL_RESULT", patched)

    def test_previous_host_only_route_is_restored_and_patch_is_idempotent(self) -> None:
        source = """#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP ();
use POSIX ();
# ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT
# ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT
my ($method, $path, $client, $req);
my $DATA_DIR = "/tmp";
if ($method eq 'POST' && $path eq '/api/audio/stream/stop') {
    # ZYKH_STATION_AUDIO_STOP_ALL
    return send_json($client, 200, release_audio_playback_device());
}
if ($method eq 'POST' && $path eq '/api/audio/speak') {
    # ZYKH_STATION_HOST_TTS_ONLY
    return send_json($client, 200, {
        ok => 0,
        disabled => 1,
        mode => 'host-offline-tts-required',
        error => 'disabled',
    });
}
sub send_json { return; }
sub run_tts_command {
    my ($cmd, $log, $timeout) = @_;
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($timeout || 90), 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        exit_code => $exit,
        detail => substr(read_text_file($log) || '', 0, 500),
    };
}
sub speak_text {
    my $requested_mode = 'offline';
    my $attempt = { command => 'true', timeout => 1 };
    my $log = '/tmp/test.log';
        my $run = run_tts_command($attempt->{command}, $log, $attempt->{timeout});
        if ($run->{ok}) {
            return { ok => JSON::PP::true };
        }
    return { ok => JSON::PP::false };
}
sub release_audio_playback_device {
    stop_audio_pcm_stream();
    system('sh', '-c', 'killall aplay 2>/dev/null');
    select(undef, undef, undef, 0.18);
    return { ok => JSON::PP::true };
}
sub stop_audio_pcm_stream { return { ok => JSON::PP::true }; }
sub shell_quote { return "''"; }
sub read_text_file { return ''; }
sub read_file_trim { return ''; }
sub write_text_file { return; }
"""
        with tempfile.TemporaryDirectory() as directory:
            gateway = Path(directory) / "server.pl"
            gateway.write_text(source, encoding="utf-8")

            subprocess.run(["perl", str(PATCHER), str(gateway)], check=True, capture_output=True, text=True)
            first = gateway.read_text(encoding="utf-8")
            subprocess.run(["perl", str(PATCHER), str(gateway)], check=True, capture_output=True, text=True)
            second = gateway.read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertIn("ZYKH_STATION_AUDIO_STOP_ALL_V2", second)
        self.assertIn("ZYKH_STATION_QSM_TTS", second)
        self.assertNotIn("host-offline-tts-required", second)
        self.assertIn("speak_text($req->{params})", second)

    def test_stop_route_cancels_tts_process_group_without_running_fallback(self) -> None:
        source = r'''#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP qw(encode_json);
use POSIX ();
# ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT
# ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT
# ZYKH_STATION_QSM_TTS
my $DATA_DIR = $ENV{TEST_DATA_DIR};
my ($method, $path, $client, $req);
sub route_request {
    if ($method eq 'POST' && $path eq '/api/audio/stream/stop') {
        return send_json($client, 200, stop_audio_pcm_stream());
    }
    if ($method eq 'POST' && $path eq '/api/audio/speak') {
        return send_json($client, 200, speak_text($req->{params}));
    }
}
sub run_tts_command {
    my ($cmd, $log, $timeout) = @_;
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($timeout || 90), 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        exit_code => $exit,
        detail => substr(read_text_file($log) || '', 0, 500),
    };
}
sub speak_text {
    my $requested_mode = 'offline';
    my @attempts = (
        { command => 'sleep 5; touch ' . shell_quote($ENV{FIRST_PLAYED}), timeout => 10 },
        { command => 'touch ' . shell_quote($ENV{FALLBACK_PLAYED}), timeout => 10 },
    );
    for my $attempt (@attempts) {
        my $log = "$DATA_DIR/audio-speak.log";
        my $run = run_tts_command($attempt->{command}, $log, $attempt->{timeout});
        if ($run->{ok}) {
            return { ok => JSON::PP::true };
        }
    }
    return { ok => JSON::PP::false };
}
sub release_audio_playback_device {
    stop_audio_pcm_stream();
    system('sh', '-c', 'killall aplay 2>/dev/null');
    select(undef, undef, undef, 0.18);
    return { ok => JSON::PP::true };
}
sub stop_audio_pcm_stream { return { ok => JSON::PP::true }; }
sub send_json { return; }
sub shell_quote {
    my ($value) = @_;
    $value =~ s/'/'"'"'/g;
    return "'$value'";
}
sub read_text_file {
    my ($path) = @_;
    return '' unless -f $path;
    open my $fh, '<', $path or return '';
    local $/;
    my $value = <$fh>;
    close $fh;
    return $value;
}
sub read_file_trim {
    my ($path) = @_;
    my $value = read_text_file($path);
    $value =~ s/^\s+|\s+$//g;
    return $value;
}
sub write_text_file {
    my ($path, $value) = @_;
    open my $fh, '>', $path or die "write $path: $!";
    print {$fh} $value;
    close $fh;
}
if (@ARGV && $ARGV[0] eq 'run') {
    print encode_json(speak_text({}));
    exit 0;
}
if (@ARGV && $ARGV[0] eq 'stop') {
    print encode_json(release_audio_playback_device());
    exit 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            first_played = root / "first-played"
            fallback_played = root / "fallback-played"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_killall = fake_bin / "killall"
            fake_killall.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_killall.chmod(0o755)
            gateway.write_text(source, encoding="utf-8")
            subprocess.run(["perl", str(PATCHER), str(gateway)], check=True, capture_output=True, text=True)

            env = {
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TEST_DATA_DIR": str(root),
                "FIRST_PLAYED": str(first_played),
                "FALLBACK_PLAYED": str(fallback_played),
            }
            runner = subprocess.Popen(
                ["perl", str(gateway), "run"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            pidfile = root / "audio-tts.pid"
            deadline = time.monotonic() + 2
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(pidfile.exists(), "managed TTS pidfile was not created")
            subprocess.run(["perl", str(gateway), "stop"], check=True, capture_output=True, text=True, env=env)
            stdout, stderr = runner.communicate(timeout=3)
            self.assertEqual(stderr, "")
            self.assertIn('"cancelled":true', stdout)
            self.assertFalse(first_played.exists())
            self.assertFalse(fallback_played.exists())


if __name__ == "__main__":
    unittest.main()
