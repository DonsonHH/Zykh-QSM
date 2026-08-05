from __future__ import annotations

import json
import os
import pty
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen


GATEWAY = Path(__file__).resolve().parents[1] / "vitals_gateway.pl"

FAKE_UART_READER = r'''#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP qw(encode_json);
use Time::HiRes qw(time sleep);

my %args;
while (@ARGV) {
    my $key = shift @ARGV;
    if ($key eq '--prewarmed') {
        $args{$key} = 1;
        next;
    }
    $args{$key} = shift @ARGV;
}

sub write_json {
    my ($path, $payload) = @_;
    open my $fh, '>:raw', $path or die "Cannot write $path: $!";
    print {$fh} encode_json($payload);
    close $fh;
}

my $mode = $ENV{FAKE_UART_MODE} || 'success';
my $session_id = $args{'--session-id'} || '';
my $state_file = $args{'--state-file'};
my $output = $args{'--output'};
my $cancel_file = $args{'--cancel-file'};
print STDERR "fake UART8 diagnostic for $session_id\n";
print STDOUT "fake UART8 output for $session_id\n";

write_json($state_file, {
    ok => JSON::PP::true,
    mode => 'real',
    session_id => $session_id,
    status => $mode eq 'wait' ? 'waiting_finger' : 'stabilizing',
    hardware_started => JSON::PP::true,
    updated_at => '2026-08-04T21:00:00+0800',
});

if ($mode eq 'wait') {
    my $deadline = time() + 5;
    sleep(0.02) while !-e $cancel_file && time() < $deadline;
}

my $success = $mode eq 'success';
my $no_frames = $mode eq 'no_frames';
write_json($output, {
    ok => $success ? JSON::PP::true : JSON::PP::false,
    status => $success ? 'measured' : 'awaiting_finger',
    heart_rate_bpm => $success ? 74 : 0,
    spo2_percent => $success ? 98 : 0,
    stable_core => $success ? JSON::PP::true : JSON::PP::false,
    communication_status => $no_frames ? 'no_protocol_frames' : 'receiving_protocol_frames',
    finger_detected => $success ? JSON::PP::true : JSON::PP::false,
    quality => $success ? 'stable' : 'no_finger',
    message => $success ? 'measurement complete' : 'waiting for finger',
    sample_count => 4,
    valid_frame_count => $no_frames ? 0 : 4,
    contact_frame_count => $success ? 4 : 0,
    heart_rate_frame_count => $success ? 4 : 0,
    spo2_frame_count => $success ? 4 : 0,
    first_heart_rate_frame => $success ? 1 : undef,
    first_spo2_frame => $success ? 1 : undef,
    spo2_stabilization_extended => JSON::PP::false,
    reference_ready => JSON::PP::false,
});
'''

FAKE_GY_READER = r'''#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP qw(encode_json);
my ($device, $output) = @ARGV;
print STDERR "fake GY-614 diagnostic for $device\n";
print STDOUT "fake GY-614 output for $device\n";
open my $fh, '>:raw', $output or die "Cannot write $output: $!";
print {$fh} encode_json({ ok => JSON::PP::true, body_temp_c => 36.6 });
close $fh;
'''


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class VitalsGatewayBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp = Path(self.temp_dir.name)
        self.uart_reader = self.temp / "fake_uart_reader.pl"
        self.gy_reader = self.temp / "fake_gy_reader.pl"
        self.uart_reader.write_text(FAKE_UART_READER, encoding="utf-8")
        self.gy_reader.write_text(FAKE_GY_READER, encoding="utf-8")
        self.master_fd, self.slave_fd = pty.openpty()
        self.process: subprocess.Popen[str] | None = None

    def tearDown(self) -> None:
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=2)
        if self.process is not None:
            if self.process.stdout is not None:
                self.process.stdout.close()
            if self.process.stderr is not None:
                self.process.stderr.close()
        os.close(self.slave_fd)
        os.close(self.master_fd)
        self.temp_dir.cleanup()

    def start_gateway(self, mode: str, *, uart_device: str | None = None) -> None:
        port = _unused_port()
        env = os.environ.copy()
        env.update(
            {
                "QSM_VITALS_PORT": str(port),
                "QSM_VITALS_HOME": str(self.temp / "gateway"),
                "QSM_VITALS_UART_READER": str(self.uart_reader),
                "QSM_GY614_READER": str(self.gy_reader),
                "GY614_UART": "fake-gy614",
                "VITALS_UART_DEVICE": uart_device or os.ttyname(self.slave_fd),
                "VITALS_UART_LOCK_FILE": str(self.temp / "vitals.lock"),
                "QSM_VITALS_DEMO_SPO2_FALLBACK": "0",
                "FAKE_UART_MODE": mode,
            }
        )
        self.process = subprocess.Popen(
            ["perl", str(GATEWAY)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        self.base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                self.fail(f"gateway exited early\nstdout={stdout}\nstderr={stderr}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.03)
        self.fail("gateway did not start")

    def request(self, method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def wait_for_terminal_status(self, session_id: str) -> dict[str, object]:
        deadline = time.monotonic() + 4
        latest: dict[str, object] = {}
        while time.monotonic() < deadline:
            latest = self.request("GET", f"/api/vitals/session/status?session_id={session_id}")
            if latest.get("status") in {"complete", "failed", "cancelled"}:
                return latest
            time.sleep(0.04)
        self.fail(f"session did not finish: {latest}")

    def test_successful_session_exposes_diagnostics_and_metric_provenance(self) -> None:
        self.start_gateway("success")

        started = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        result = self.wait_for_terminal_status(str(started["session_id"]))

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["temperature"], 36.6)
        self.assertEqual(result["heart_rate"], 74)
        self.assertEqual(result["spo2"], 98)
        self.assertEqual(result["temperature_source"], "gy614_sensor")
        self.assertEqual(result["heart_rate_source"], "uart8_sensor")
        self.assertEqual(result["spo2_source"], "uart8_sensor")
        self.assertTrue(result["stable_core"])
        self.assertEqual(result["communication_status"], "receiving_protocol_frames")
        self.assertEqual(result["valid_frame_count"], 4)
        self.assertIsNone(result["failure_reason"])

    def test_reader_output_is_retained_in_per_session_logs(self) -> None:
        self.start_gateway("success")

        started = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        session_id = str(started["session_id"])
        self.wait_for_terminal_status(session_id)

        log_dir = self.temp / "gateway" / "logs"
        uart_log = log_dir / f"{session_id}-uart8.log"
        gy_log = log_dir / f"{session_id}-gy614.log"
        uart_log_text = uart_log.read_text(encoding="utf-8")
        gy_log_text = gy_log.read_text(encoding="utf-8")
        self.assertIn("fake UART8 diagnostic", uart_log_text)
        self.assertIn("fake UART8 output", uart_log_text)
        self.assertIn("fake GY-614 diagnostic", gy_log_text)
        self.assertIn("fake GY-614 output", gy_log_text)

    def test_missing_gy614_reader_is_recorded_in_the_session_log(self) -> None:
        self.gy_reader.unlink()
        self.start_gateway("success")

        started = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        session_id = str(started["session_id"])
        result = self.wait_for_terminal_status(session_id)

        gy_log = self.temp / "gateway" / "logs" / f"{session_id}-gy614.log"
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "temperature_unavailable")
        self.assertIn("GY-614 reader not found", gy_log.read_text(encoding="utf-8"))
        self.assertIn(str(self.gy_reader), gy_log.read_text(encoding="utf-8"))

    def test_no_finger_session_reports_transport_health_and_specific_failure(self) -> None:
        self.start_gateway("no_finger")

        started = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        result = self.wait_for_terminal_status(str(started["session_id"]))

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["stable_core"])
        self.assertFalse(result["finger_detected"])
        self.assertEqual(result["communication_status"], "receiving_protocol_frames")
        self.assertEqual(result["valid_frame_count"], 4)
        self.assertEqual(result["heart_rate_frame_count"], 0)
        self.assertEqual(result["spo2_frame_count"], 0)
        self.assertEqual(result["failure_reason"], "no_finger")
        self.assertIn("未检测到稳定的手指信号", result["error_message"])

    def test_no_protocol_frames_is_not_misreported_as_no_finger(self) -> None:
        self.start_gateway("no_frames")

        started = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        result = self.wait_for_terminal_status(str(started["session_id"]))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["communication_status"], "no_protocol_frames")
        self.assertEqual(result["valid_frame_count"], 0)
        self.assertEqual(result["failure_reason"], "no_protocol_frames")
        self.assertNotEqual(result["failure_reason"], "no_finger")

    def test_unknown_session_exposes_gateway_and_failure_diagnostics(self) -> None:
        self.start_gateway("success")

        result = self.request(
            "GET",
            "/api/vitals/session/status?session_id=vitals-missing",
        )

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["communication_status"], "gateway_available")
        self.assertEqual(result["failure_reason"], "session_not_found")

    def test_cancelled_measurement_is_not_classified_as_failure(self) -> None:
        self.start_gateway("wait")

        started = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        cancel_file = self.temp / "gateway" / "data" / f"{started['session_id']}-cancel"
        cancel_file.write_text("cancel requested", encoding="utf-8")
        result = self.wait_for_terminal_status(str(started["session_id"]))

        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result.get("failure_reason"))

    def test_replacing_an_active_session_cancels_the_old_session_with_reason(self) -> None:
        self.start_gateway("wait")

        first = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        second = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        first_status = self.request(
            "GET",
            f"/api/vitals/session/status?session_id={first['session_id']}",
        )

        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual(first_status["status"], "cancelled")
        self.assertEqual(first_status["cancel_reason"], "replaced")
        self.assertIsNone(first_status.get("failure_reason"))
        self.assertFalse(first_status["hardware_started"])
        self.assertTrue(second["hardware_started"])

        cancelled = self.request(
            "POST",
            "/api/vitals/session/cancel",
            {"session_id": second["session_id"]},
        )
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(cancelled.get("failure_reason"))

    def test_cancel_preserves_uart_stop_failure_diagnostics(self) -> None:
        self.start_gateway("wait", uart_device=str(self.temp / "missing-uart"))

        started = self.request("POST", "/api/vitals/session/start", {"replace_active": True})
        cancelled = self.request(
            "POST",
            "/api/vitals/session/cancel",
            {"session_id": started["session_id"]},
        )

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["communication_status"], "gateway_available")
        self.assertEqual(cancelled["failure_reason"], "uart_device_missing")
        self.assertIn("does not exist", cancelled["error_message"])


if __name__ == "__main__":
    unittest.main()
