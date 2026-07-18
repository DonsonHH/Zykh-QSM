from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


PATCHER = Path(__file__).resolve().parents[1] / "patch_station_gateway.pl"


class StationGatewayPatchTest(unittest.TestCase):
    def test_empty_request_exits_child_instead_of_reentering_accept_loop(self) -> None:
        source = """#!/usr/bin/env perl
use strict;
use warnings;
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
if ($method eq 'POST' && $path eq '/api/audio/stream/stop') {
    return send_json($client, 200, stop_audio_pcm_stream());
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
        self.assertIn("release_audio_playback_device()", patched)


if __name__ == "__main__":
    unittest.main()
