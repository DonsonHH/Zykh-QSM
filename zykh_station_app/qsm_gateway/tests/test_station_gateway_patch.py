from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


PATCHER = Path(__file__).resolve().parents[1] / "patch_station_gateway.pl"
LEGACY_GATEWAY = Path(__file__).resolve().parents[3] / "zykh_app" / "server.pl"


DISPENSE_GATEWAY_FIXTURE = r'''#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use JSON::PP qw(encode_json decode_json);
# ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT
# ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT
# ZYKH_STATION_AUDIO_STOP_ALL_V2
# ZYKH_STATION_QSM_TTS
# ZYKH_STATION_TTS_PROCESS_GROUP
# ZYKH_STATION_TTS_CANCEL_HELPER
# ZYKH_STATION_RELEASE_CANCELS_TTS
# ZYKH_STATION_TTS_CANCEL_RESULT
my $DATA_DIR = $ENV{TEST_DATA_DIR};

sub route_request {
    my ($method, $path, $params) = @_;
    die "unexpected route" unless $method eq 'POST' && $path eq '/api/dispense';
    return dispense($params);
}

sub dispense {
    my ($p) = @_;
    my $slot = int($p->{slot} || 0);
    return { ok => JSON::PP::false, error => 'slot required' } if $slot <= 0;
    my $control_code = exists $p->{control_code} && "$p->{control_code}" =~ /^\d+$/
        ? int($p->{control_code})
        : cabinet_control_code($slot);
    my $gpio = $ENV{"SLOT${slot}_GPIO"};
    my $uart_dev = $ENV{DISPENSE_UART} || '';
    my ($result, $detail) = ('success', 'simulated');
    if ($uart_dev && -e $uart_dev && ($ENV{DISPENSE_MODE} || 'uart') eq 'uart') {
        my $r = dispense_uart($uart_dev, $slot, $control_code);
        ($result, $detail) = $r->{ok} ? ('success', $r->{detail}) : ('failed', $r->{error});
    } elsif (defined $gpio && $gpio =~ /^\d+$/) {
        my $r = pulse_gpio($gpio, 500);
        ($result, $detail) = $r->{ok} ? ('success', $r->{detail}) : ('failed', $r->{error});
    }
    return {
        ok => $result eq 'success' ? JSON::PP::true : JSON::PP::false,
        result => $result,
        detail => $detail,
        slot => $slot,
        control_code => $control_code,
        records => [],
        medicines => [],
    };
}

sub cabinet_control_code {
    my ($slot) = @_;
    return 13 if $slot == 13;
    return $slot - 1;
}

sub persisted_operation_state {
    my @paths = sort glob("$DATA_DIR/dispense-operation-*.json");
    return 'missing' unless @paths;
    open my $fh, '<:raw', $paths[-1] or return 'unreadable';
    local $/;
    my $raw = <$fh>;
    close $fh;
    my $state = eval { decode_json($raw) };
    return ref($state) eq 'HASH' ? ($state->{state} || 'empty') : 'invalid';
}

sub append_hardware_log {
    my ($kind, $slot, $control_code) = @_;
    open my $fh, '>>', "$DATA_DIR/hardware.log" or die "hardware log: $!";
    print {$fh} join(' ', $kind, "state=" . persisted_operation_state(), "slot=$slot", "control=$control_code") . "\n";
    close $fh;
}

sub dispense_uart {
    my ($dev, $slot, $control_code) = @_;
    my $delay = 0 + ($ENV{FAKE_HARDWARE_DELAY} || 0);
    select(undef, undef, undef, $delay) if $delay > 0;
    append_hardware_log('uart', $slot, $control_code);
    die "fake UART result lost\n" if $ENV{FAKE_HARDWARE_DIE};
    return { ok => JSON::PP::true, detail => "uart pulse $control_code" };
}

sub pulse_gpio {
    my ($gpio, $ms) = @_;
    append_hardware_log('gpio', $gpio, $ms);
    return { ok => JSON::PP::true, detail => "gpio pulse $gpio" };
}

sub now_text { return '2026-08-10 18:00:00'; }

if (@ARGV) {
    my $params = decode_json($ARGV[0]);
    print encode_json(route_request('POST', '/api/dispense', $params));
    exit 0;
}
'''


class StationGatewayPatchTest(unittest.TestCase):
    def test_empty_request_exits_child_instead_of_reentering_accept_loop(self) -> None:
        source = """#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP ();
use POSIX ();
# ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1
# ZYKH_STATION_DISPENSE_HARDWARE_SEAM_V2
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
# ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1
# ZYKH_STATION_DISPENSE_HARDWARE_SEAM_V2
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
# ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1
# ZYKH_STATION_DISPENSE_HARDWARE_SEAM_V2
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

    def test_dispense_operation_id_replays_success_without_second_uart_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            uart = root / "fake-uart"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            uart.write_bytes(b"")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(uart),
            })
            payload = {
                "slot": 13,
                "quantity": 1,
                "control_code": 13,
                "operation_id": "manual-dispense-op-001",
            }
            first = json.loads(subprocess.run(
                ["perl", str(gateway), json.dumps(payload)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout)
            replay = json.loads(subprocess.run(
                ["perl", str(gateway), json.dumps(payload)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout)
            hardware_lines = (root / "hardware.log").read_text(encoding="utf-8").splitlines()

        self.assertTrue(first["ok"])
        self.assertEqual(first["result"], "success")
        self.assertEqual(first["operation_id"], "manual-dispense-op-001")
        self.assertFalse(first["replay"])
        self.assertEqual(replay["result"], first["result"])
        self.assertEqual(replay["detail"], first["detail"])
        self.assertTrue(replay["replay"])
        self.assertEqual(hardware_lines, ["uart state=sent slot=13 control=13"])

    def test_zero_control_code_is_sent_once_over_uart_and_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            uart = root / "fake-uart"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            uart.write_bytes(b"")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(uart),
            })
            payload = {
                "slot": 4,
                "quantity": 1,
                "control_code": 0,
                "operation_id": "manual-dispense-op-zero",
            }
            responses = [json.loads(subprocess.run(
                ["perl", str(gateway), json.dumps(payload)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout) for _ in range(2)]
            hardware_lines = (root / "hardware.log").read_text(encoding="utf-8").splitlines()

        self.assertTrue(responses[0]["ok"])
        self.assertFalse(responses[0]["replay"])
        self.assertTrue(responses[1]["ok"])
        self.assertTrue(responses[1]["replay"])
        self.assertEqual(hardware_lines, ["uart state=sent slot=4 control=0"])

    def test_real_dispense_without_uart_or_gpio_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(root / "missing-uart"),
            })

            response = json.loads(subprocess.run(
                ["perl", str(gateway), json.dumps({
                    "slot": 13,
                    "quantity": 1,
                    "operation_id": "manual-no-executor",
                })],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout)
            hardware_log_exists = (root / "hardware.log").exists()

        self.assertFalse(response["ok"])
        self.assertEqual(response["result"], "hardware_unavailable")
        self.assertFalse(response.get("result_unknown", False))
        self.assertFalse(hardware_log_exists)

    def test_different_operation_ids_are_serialized_at_the_hardware_seam(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            uart = root / "fake-uart"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            uart.write_bytes(b"")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(uart),
                "FAKE_HARDWARE_DELAY": "0.30",
            })
            started_at = time.monotonic()
            processes = [
                subprocess.Popen(
                    ["perl", str(gateway), json.dumps({
                        "slot": slot,
                        "quantity": 1,
                        "operation_id": f"parallel-operation-{slot}",
                    })],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
                for slot in (12, 13)
            ]
            results = [json.loads(process.communicate(timeout=3)[0]) for process in processes]
            elapsed = time.monotonic() - started_at
            hardware_lines = (root / "hardware.log").read_text(encoding="utf-8").splitlines()

        self.assertTrue(all(result["ok"] for result in results))
        self.assertEqual(len(hardware_lines), 2)
        self.assertGreaterEqual(elapsed, 0.52)

    def test_same_operation_id_with_different_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            uart = root / "fake-uart"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            uart.write_bytes(b"")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(uart),
            })
            original = {
                "slot": 13,
                "quantity": 1,
                "control_code": 13,
                "operation_id": "manual-dispense-op-conflict",
            }

            def invoke(payload: dict[str, object]) -> dict[str, object]:
                return json.loads(subprocess.run(
                    ["perl", str(gateway), json.dumps(payload)],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                ).stdout)

            self.assertTrue(invoke(original)["ok"])
            conflicts = [
                invoke({**original, "slot": 12}),
                invoke({**original, "quantity": 2}),
                invoke({**original, "control_code": 12}),
            ]
            hardware_lines = (root / "hardware.log").read_text(encoding="utf-8").splitlines()

        for conflict in conflicts:
            self.assertFalse(conflict["ok"])
            self.assertEqual(conflict["result"], "idempotency_conflict")
            self.assertTrue(conflict["idempotency_conflict"])
        self.assertEqual(hardware_lines, ["uart state=sent slot=13 control=13"])

    def test_reserved_or_sent_operation_without_final_result_is_never_retried(self) -> None:
        for previous_state in ("reserved", "sent"):
            with self.subTest(previous_state=previous_state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                gateway = root / "server.pl"
                uart = root / "fake-uart"
                gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
                uart.write_bytes(b"")
                subprocess.run(
                    ["perl", str(PATCHER), str(gateway)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                operation_id = f"manual-dispense-op-{previous_state}"
                state_path = root / f"dispense-operation-{operation_id}.json"
                state_path.write_text(json.dumps({
                    "schema_version": 1,
                    "operation_id": operation_id,
                    "slot": 13,
                    "quantity": 1,
                    "control_code": 13,
                    "state": previous_state,
                    "created_at": "2026-08-10 17:59:00",
                    "updated_at": "2026-08-10 17:59:00",
                }), encoding="utf-8")
                env = os.environ.copy()
                env.update({
                    "TEST_DATA_DIR": str(root),
                    "DISPENSE_MODE": "uart",
                    "DISPENSE_UART": str(uart),
                })
                payload = {
                    "slot": 13,
                    "quantity": 1,
                    "control_code": 13,
                    "operation_id": operation_id,
                }
                responses = [json.loads(subprocess.run(
                    ["perl", str(gateway), json.dumps(payload)],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                ).stdout) for _ in range(2)]

                self.assertFalse((root / "hardware.log").exists())
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["state"], previous_state)
                for response in responses:
                    self.assertFalse(response["ok"])
                    self.assertEqual(response["result"], "result_unknown")
                    self.assertTrue(response["result_unknown"])
                    self.assertFalse(response["retry_safe"])

    def test_dispense_without_operation_id_keeps_legacy_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            uart = root / "fake-uart"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            uart.write_bytes(b"")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(uart),
            })
            payload = {"slot": 13, "quantity": 1, "control_code": 13}
            responses = [json.loads(subprocess.run(
                ["perl", str(gateway), json.dumps(payload)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout) for _ in range(2)]
            hardware_lines = (root / "hardware.log").read_text(encoding="utf-8").splitlines()
            state_files = list(root.glob("dispense-operation-*.json"))

        self.assertTrue(all(response["ok"] for response in responses))
        self.assertTrue(all("operation_id" not in response for response in responses))
        self.assertTrue(all("replay" not in response for response in responses))
        self.assertEqual(len(hardware_lines), 2)
        self.assertEqual(state_files, [])

    def test_concurrent_same_operation_id_runs_hardware_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            uart = root / "fake-uart"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            uart.write_bytes(b"")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(uart),
                "FAKE_HARDWARE_DELAY": "0.25",
            })
            payload = json.dumps({
                "slot": 13,
                "quantity": 1,
                "control_code": 13,
                "operation_id": "manual-dispense-op-concurrent",
            })
            runners = [subprocess.Popen(
                ["perl", str(gateway), payload],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            ) for _ in range(2)]
            results = [runner.communicate(timeout=3) for runner in runners]
            responses = [json.loads(stdout) for stdout, _ in results]
            hardware_lines = (root / "hardware.log").read_text(encoding="utf-8").splitlines()

        self.assertTrue(all(runner.returncode == 0 for runner in runners))
        self.assertTrue(all(stderr == "" for _, stderr in results))
        self.assertEqual(sum(response["replay"] is False for response in responses), 1)
        self.assertEqual(sum(response["replay"] is True for response in responses), 1)
        self.assertEqual(hardware_lines, ["uart state=sent slot=13 control=13"])

    def test_lost_uart_result_stays_unknown_and_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = root / "server.pl"
            uart = root / "fake-uart"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            uart.write_bytes(b"")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            env = os.environ.copy()
            env.update({
                "TEST_DATA_DIR": str(root),
                "DISPENSE_MODE": "uart",
                "DISPENSE_UART": str(uart),
                "FAKE_HARDWARE_DIE": "1",
            })
            payload = json.dumps({
                "slot": 13,
                "quantity": 1,
                "control_code": 13,
                "operation_id": "manual-dispense-op-lost-result",
            })
            responses = [json.loads(subprocess.run(
                ["perl", str(gateway), payload],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout) for _ in range(2)]
            state = json.loads(next(root.glob("dispense-operation-*.json")).read_text(encoding="utf-8"))
            hardware_lines = (root / "hardware.log").read_text(encoding="utf-8").splitlines()

        self.assertEqual(state["state"], "sent")
        self.assertEqual(hardware_lines, ["uart state=sent slot=13 control=13"])
        self.assertTrue(all(response["result_unknown"] for response in responses))
        self.assertTrue(all(response["result"] == "result_unknown" for response in responses))

    def test_dispense_idempotency_patch_is_repeatable_and_perl_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            gateway = Path(directory) / "server.pl"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            first = gateway.read_text(encoding="utf-8")
            second_patch = subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            second = gateway.read_text(encoding="utf-8")
            syntax = subprocess.run(
                ["perl", "-c", str(gateway)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(first, second)
        self.assertIn("ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1", second)
        self.assertIn("ZYKH_STATION_DISPENSE_OPERATION_DURABLE_V2", second)
        writer = second.split("sub write_dispense_operation_state", 1)[1].split(
            "sub dispense_operation_unknown_result", 1
        )[0]
        self.assertIn("require IO::Handle", writer)
        self.assertIn("$fh->flush()", writer)
        self.assertIn("$fh->sync()", writer)
        self.assertIn("rename $temporary, $path", writer)
        self.assertIn("open my $directory", writer)
        self.assertIn("$directory->sync()", writer)
        self.assertLess(writer.index("$fh->sync()"), writer.index("rename $temporary, $path"))
        self.assertLess(writer.index("rename $temporary, $path"), writer.index("$directory->sync()"))
        self.assertIn("already installed", second_patch.stdout)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_existing_idempotency_patch_is_upgraded_to_durable_state_writes(self) -> None:
        legacy_writer = r'''sub write_dispense_operation_state {
    my ($path, $state) = @_;
    my $encoded = eval { JSON::PP::encode_json($state) };
    return (0, "无法编码出药预留：$@") unless defined $encoded;
    my $temporary = "$path.tmp.$$";
    open my $fh, '>:raw', $temporary
        or return (0, "无法创建出药预留：$!");
    if (!print {$fh} $encoded) {
        my $error = $!;
        close $fh;
        unlink $temporary;
        return (0, "无法写入出药预留：$error");
    }
    if (!close $fh) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法落盘出药预留：$error");
    }
    if (!rename $temporary, $path) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法提交出药预留：$error");
    }
    return (1, '');
}
'''
        with tempfile.TemporaryDirectory() as directory:
            gateway = Path(directory) / "server.pl"
            gateway.write_text(DISPENSE_GATEWAY_FIXTURE, encoding="utf-8")
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            installed = gateway.read_text(encoding="utf-8")
            writer_start = installed.index("# ZYKH_STATION_DISPENSE_OPERATION_DURABLE_V2")
            writer_end = installed.index("sub dispense_operation_unknown_result", writer_start)
            gateway.write_text(
                installed[:writer_start] + legacy_writer + "\n" + installed[writer_end:],
                encoding="utf-8",
            )

            upgraded = subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            source = gateway.read_text(encoding="utf-8")
            syntax = subprocess.run(
                ["perl", "-c", str(gateway)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertIn("Installed station gateway reliability fixes.", upgraded.stdout)
        self.assertIn("ZYKH_STATION_DISPENSE_OPERATION_DURABLE_V2", source)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_real_legacy_gateway_copy_patches_without_modifying_source(self) -> None:
        original = LEGACY_GATEWAY.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            gateway = Path(directory) / "server.pl"
            gateway.write_bytes(original)
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            first = gateway.read_bytes()
            subprocess.run(
                ["perl", str(PATCHER), str(gateway)],
                check=True,
                capture_output=True,
                text=True,
            )
            second = gateway.read_bytes()
            syntax = subprocess.run(
                ["perl", "-c", str(gateway)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(first, second)
        self.assertIn(b"ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1", second)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        self.assertEqual(LEGACY_GATEWAY.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
