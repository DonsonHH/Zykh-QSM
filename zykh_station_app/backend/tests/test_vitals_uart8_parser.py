from __future__ import annotations

import json
import os
import pty
import select
import subprocess
import tempfile
import threading
import time
import unittest
import fcntl
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARSER = PROJECT_ROOT / "qsm_gateway" / "read_vitals_uart8.pl"


def frame(
    *,
    heart_rate: int,
    spo2: int,
    systolic: int,
    diastolic: int,
    respiratory_rate: int,
    microcirculation: int = 5,
    fatigue: int = 22,
    rr_interval: int = 81,
    hrv_sdnn: int = 43,
    hrv_rmssd: int = 31,
    body_temperature: tuple[int, int] = (0, 0),
    ambient_temperature: tuple[int, int] = (26, 37),
) -> bytes:
    return bytes(
        [
            0xFF,
            0x01,
            heart_rate,
            spo2,
            microcirculation,
            systolic,
            diastolic,
            respiratory_rate,
            fatigue,
            rr_interval,
            hrv_sdnn,
            hrv_rmssd,
            body_temperature[0],
            body_temperature[1],
            ambient_temperature[0],
            ambient_temperature[1],
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0xF1,
        ]
    )


class VitalsUart8ParserTest(unittest.TestCase):
    def test_prewarmed_measurement_uses_fresh_frames_and_a_minimum_window(self) -> None:
        measured = frame(
            heart_rate=74,
            spo2=98,
            systolic=0,
            diastolic=0,
            respiratory_rate=16,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output = temp / "vitals.json"
            lock_path = temp / "vitals.lock"
            master_fd, slave_fd = pty.openpty()
            slave_name = os.ttyname(slave_fd)
            commands: list[int] = []
            stopped = threading.Event()

            def emulate_sensor() -> None:
                last_frame_at = 0.0
                deadline = time.monotonic() + 4
                while not stopped.is_set() and time.monotonic() < deadline:
                    readable, _, _ = select.select([master_fd], [], [], 0.02)
                    if readable:
                        try:
                            commands.extend(os.read(master_fd, 128))
                        except OSError:
                            break
                    now = time.monotonic()
                    if now - last_frame_at < 0.12:
                        continue
                    try:
                        os.write(master_fd, measured)
                    except OSError:
                        break
                    last_frame_at = now

            worker = threading.Thread(target=emulate_sensor, daemon=True)
            worker.start()
            env = os.environ.copy()
            env["VITALS_UART_LOCK_FILE"] = str(lock_path)
            started_at = time.monotonic()
            try:
                completed = subprocess.run(
                    [
                        "perl",
                        str(PARSER),
                        "--device",
                        slave_name,
                        "--timeout",
                        "2",
                        "--stable-frames",
                        "2",
                        "--minimum-measurement-seconds",
                        "0.7",
                        "--minimum-contact-seconds",
                        "0.5",
                        "--prewarmed",
                        "--output",
                        str(output),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=5,
                )
                elapsed = time.monotonic() - started_at
            finally:
                stopped.set()
                worker.join(timeout=1)
                os.close(slave_fd)
                os.close(master_fd)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn(0x24, commands, "a prewarmed run must not restart the sensor algorithm")
        self.assertGreaterEqual(elapsed, 0.65)
        self.assertGreaterEqual(payload["heart_rate_frame_count"], 2)
        self.assertGreaterEqual(payload["spo2_frame_count"], 2)

    def test_valid_waiting_frames_do_not_restart_sensor_before_spo2_stabilizes(self) -> None:
        no_finger = frame(
            heart_rate=0,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
        )
        measured = frame(
            heart_rate=74,
            spo2=98,
            systolic=0,
            diastolic=0,
            respiratory_rate=16,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output = temp / "vitals.json"
            lock_path = temp / "vitals.lock"
            master_fd, slave_fd = pty.openpty()
            slave_name = os.ttyname(slave_fd)
            commands: list[int] = []
            stopped = threading.Event()

            def emulate_sensor() -> None:
                measurement_started_at: float | None = None
                last_frame_at = 0.0
                deadline = time.monotonic() + 7
                while not stopped.is_set() and time.monotonic() < deadline:
                    readable, _, _ = select.select([master_fd], [], [], 0.02)
                    if readable:
                        try:
                            command_bytes = os.read(master_fd, 128)
                        except OSError:
                            break
                        for command in command_bytes:
                            commands.append(command)
                            if command == 0x24:
                                measurement_started_at = time.monotonic()
                    now = time.monotonic()
                    if measurement_started_at is None or now - last_frame_at < 0.15:
                        continue
                    payload = measured if now - measurement_started_at >= 2.4 else no_finger
                    try:
                        os.write(master_fd, payload)
                    except OSError:
                        break
                    last_frame_at = now

            worker = threading.Thread(target=emulate_sensor, daemon=True)
            worker.start()
            env = os.environ.copy()
            env["VITALS_UART_LOCK_FILE"] = str(lock_path)
            try:
                completed = subprocess.run(
                    [
                        "perl",
                        str(PARSER),
                        "--device",
                        slave_name,
                        "--timeout",
                        "4",
                        "--stable-frames",
                        "2",
                        "--output",
                        str(output),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=8,
                )
            finally:
                stopped.set()
                worker.join(timeout=1)
                os.close(slave_fd)
                os.close(master_fd)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(commands.count(0x24), 1, "valid protocol frames must not trigger a sensor restart")
        self.assertEqual(payload["heart_rate_bpm"], 74)
        self.assertEqual(payload["spo2_percent"], 98)
        self.assertTrue(payload["finger_detected"])

    def test_timeout_with_valid_zero_frames_reports_no_finger_instead_of_transport_failure(self) -> None:
        no_finger = frame(
            heart_rate=0,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output = temp / "vitals.json"
            lock_path = temp / "vitals.lock"
            master_fd, slave_fd = pty.openpty()
            slave_name = os.ttyname(slave_fd)
            started = threading.Event()
            stopped = threading.Event()

            def emulate_sensor() -> None:
                last_frame_at = 0.0
                deadline = time.monotonic() + 3
                while not stopped.is_set() and time.monotonic() < deadline:
                    readable, _, _ = select.select([master_fd], [], [], 0.02)
                    if readable:
                        try:
                            if 0x24 in os.read(master_fd, 128):
                                started.set()
                        except OSError:
                            break
                    now = time.monotonic()
                    if not started.is_set() or now - last_frame_at < 0.08:
                        continue
                    try:
                        os.write(master_fd, no_finger)
                    except OSError:
                        break
                    last_frame_at = now

            worker = threading.Thread(target=emulate_sensor, daemon=True)
            worker.start()
            env = os.environ.copy()
            env["VITALS_UART_LOCK_FILE"] = str(lock_path)
            started_at = time.monotonic()
            try:
                completed = subprocess.run(
                    [
                        "perl",
                        str(PARSER),
                        "--device",
                        slave_name,
                        "--timeout",
                        "1",
                        "--stabilization-grace",
                        "0",
                        "--spo2-grace",
                        "0",
                        "--minimum-measurement-seconds",
                        "0",
                        "--minimum-contact-seconds",
                        "0",
                        "--output",
                        str(output),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=4,
                )
                elapsed = time.monotonic() - started_at
            finally:
                stopped.set()
                worker.join(timeout=1)
                os.close(slave_fd)
                os.close(master_fd)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertEqual(payload["status"], "awaiting_finger")
        self.assertFalse(payload["stable_core"])
        self.assertFalse(payload["finger_detected"])
        self.assertEqual(payload["communication_status"], "receiving_protocol_frames")
        self.assertGreater(payload["valid_frame_count"], 0)
        self.assertEqual(payload["heart_rate_frame_count"], 0)
        self.assertEqual(payload["spo2_frame_count"], 0)

    def test_extends_only_after_contact_when_spo2_needs_more_time(self) -> None:
        no_finger = frame(
            heart_rate=0,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
        )
        heart_rate_only = frame(
            heart_rate=76,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            body_temperature=(36, 42),
        )
        measured = frame(
            heart_rate=76,
            spo2=97,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            body_temperature=(36, 45),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output = temp / "vitals.json"
            lock_path = temp / "vitals.lock"
            master_fd, slave_fd = pty.openpty()
            slave_name = os.ttyname(slave_fd)
            stopped = threading.Event()
            os.write(master_fd, measured)

            def emulate_sensor() -> None:
                measurement_started_at: float | None = None
                last_frame_at = 0.0
                deadline = time.monotonic() + 5
                while not stopped.is_set() and time.monotonic() < deadline:
                    readable, _, _ = select.select([master_fd], [], [], 0.02)
                    if readable:
                        try:
                            command_bytes = os.read(master_fd, 128)
                        except OSError:
                            break
                        if 0x24 in command_bytes:
                            measurement_started_at = time.monotonic()
                    now = time.monotonic()
                    if measurement_started_at is None or now - last_frame_at < 0.12:
                        continue
                    elapsed = now - measurement_started_at
                    payload = measured if elapsed >= 1.75 else heart_rate_only if elapsed >= 1.25 else no_finger
                    try:
                        os.write(master_fd, payload)
                    except OSError:
                        break
                    last_frame_at = now

            worker = threading.Thread(target=emulate_sensor, daemon=True)
            worker.start()
            env = os.environ.copy()
            env["VITALS_UART_LOCK_FILE"] = str(lock_path)
            try:
                completed = subprocess.run(
                    [
                        "perl",
                        str(PARSER),
                        "--device",
                        slave_name,
                        "--timeout",
                        "1.5",
                        "--stabilization-grace",
                        "1",
                        "--stable-frames",
                        "2",
                        "--output",
                        str(output),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=6,
                )
            finally:
                stopped.set()
                worker.join(timeout=1)
                os.close(slave_fd)
                os.close(master_fd)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["heart_rate_bpm"], 76)
        self.assertEqual(payload["spo2_percent"], 97)
        self.assertGreater(payload["first_heart_rate_frame"], 1, "stale pre-session input must be flushed")
        self.assertGreater(payload["first_spo2_frame"], payload["first_heart_rate_frame"])

    def test_extends_once_when_heart_rate_is_stable_but_spo2_is_still_calculating(self) -> None:
        heart_rate_only = frame(
            heart_rate=78,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            body_temperature=(36, 31),
        )
        measured = frame(
            heart_rate=78,
            spo2=98,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            body_temperature=(36, 34),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output = temp / "vitals.json"
            lock_path = temp / "vitals.lock"
            master_fd, slave_fd = pty.openpty()
            slave_name = os.ttyname(slave_fd)
            stopped = threading.Event()

            def emulate_sensor() -> None:
                measurement_started_at: float | None = None
                last_frame_at = 0.0
                deadline = time.monotonic() + 4
                while not stopped.is_set() and time.monotonic() < deadline:
                    readable, _, _ = select.select([master_fd], [], [], 0.02)
                    if readable:
                        try:
                            command_bytes = os.read(master_fd, 128)
                        except OSError:
                            break
                        if 0x24 in command_bytes:
                            measurement_started_at = time.monotonic()
                    now = time.monotonic()
                    if measurement_started_at is None or now - last_frame_at < 0.12:
                        continue
                    payload = measured if now - measurement_started_at >= 1.15 else heart_rate_only
                    try:
                        os.write(master_fd, payload)
                    except OSError:
                        break
                    last_frame_at = now

            worker = threading.Thread(target=emulate_sensor, daemon=True)
            worker.start()
            env = os.environ.copy()
            env["VITALS_UART_LOCK_FILE"] = str(lock_path)
            try:
                completed = subprocess.run(
                    [
                        "perl",
                        str(PARSER),
                        "--device",
                        slave_name,
                        "--timeout",
                        "0.8",
                        "--stabilization-grace",
                        "0",
                        "--spo2-grace",
                        "1.2",
                        "--minimum-measurement-seconds",
                        "0",
                        "--minimum-contact-seconds",
                        "0",
                        "--stable-frames",
                        "2",
                        "--output",
                        str(output),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=5,
                )
            finally:
                stopped.set()
                worker.join(timeout=1)
                os.close(slave_fd)
                os.close(master_fd)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(payload["stable_core"])
        self.assertTrue(payload["spo2_stabilization_extended"])
        self.assertEqual(payload["spo2_percent"], 98)

    def test_recovers_a_valid_measurement_from_fragmented_uart_data(self) -> None:
        no_finger = frame(
            heart_rate=0,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
        )
        measured = frame(
            heart_rate=74,
            spo2=98,
            systolic=119,
            diastolic=78,
            respiratory_rate=16,
            body_temperature=(36, 55),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            fixture.write_bytes(b"\x00\x7e\xaa" + no_finger + measured)

            completed = subprocess.run(
                [
                    "perl",
                    str(PARSER),
                    "--input-file",
                    str(fixture),
                    "--chunk-size",
                    "7",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["heart_rate_bpm"], 74)
        self.assertEqual(payload["spo2_percent"], 98)
        self.assertEqual(payload["systolic_pressure"], 119)
        self.assertEqual(payload["diastolic_pressure"], 78)
        self.assertEqual(payload["respiratory_rate"], 16)
        self.assertTrue(payload["finger_detected"])
        self.assertEqual(payload["quality"], "poor_signal")
        self.assertEqual(payload["body_temperature_raw"], {"integer": 36, "decimal": 55})
        self.assertEqual(payload["valid_frame_count"], 2)

    def test_aggregates_heart_rate_and_spo2_that_stabilize_in_separate_frames(self) -> None:
        heart_rate_only = frame(
            heart_rate=72,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            body_temperature=(36, 28),
        )
        spo2_only = frame(
            heart_rate=0,
            spo2=98,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            body_temperature=(36, 31),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            fixture.write_bytes(heart_rate_only * 3 + spo2_only * 3)
            completed = subprocess.run(
                [
                    "perl",
                    str(PARSER),
                    "--input-file",
                    str(fixture),
                    "--chunk-size",
                    "24",
                    "--stable-frames",
                    "3",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["finger_detected"])
        self.assertEqual(payload["quality"], "stable")
        self.assertEqual(payload["heart_rate_bpm"], 72)
        self.assertEqual(payload["spo2_percent"], 98)
        self.assertEqual(payload["heart_rate_frame_count"], 3)
        self.assertEqual(payload["spo2_frame_count"], 3)
        self.assertEqual(payload["first_contact_frame"], 1)
        self.assertEqual(payload["first_heart_rate_frame"], 1)
        self.assertEqual(payload["first_spo2_frame"], 4)
        self.assertEqual([item["frame"] for item in payload["signal_trace"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual([item["spo2"] for item in payload["signal_trace"]], [0, 0, 0, 98, 98, 98])

    def test_scattered_old_core_values_are_not_reported_as_a_stable_measurement(self) -> None:
        measured = frame(
            heart_rate=76,
            spo2=98,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            body_temperature=(36, 20),
        )
        no_signal = frame(
            heart_rate=0,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            fixture.write_bytes(measured + no_signal * 6 + measured)
            completed = subprocess.run(
                [
                    "perl",
                    str(PARSER),
                    "--input-file",
                    str(fixture),
                    "--chunk-size",
                    str(24 * 8),
                    "--stable-frames",
                    "2",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertTrue(payload["ok"], "the parser may preserve the last nonzero diagnostic values")
        self.assertFalse(payload["stable_core"], "scattered values must not complete a gateway session")
        self.assertEqual(payload["quality"], "poor_signal")
        self.assertEqual(payload["communication_status"], "receiving_protocol_frames")

    def test_one_isolated_fingertip_temperature_does_not_claim_finger_contact(self) -> None:
        temperature_only = frame(
            heart_rate=0,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
            body_temperature=(36, 72),
        )
        no_signal = frame(
            heart_rate=0,
            spo2=0,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            fixture.write_bytes(temperature_only + no_signal * 3)
            subprocess.run(
                [
                    "perl",
                    str(PARSER),
                    "--input-file",
                    str(fixture),
                    "--chunk-size",
                    str(24 * 4),
                    "--stable-frames",
                    "2",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(payload["finger_detected"])
        self.assertEqual(payload["quality"], "no_finger")
        self.assertEqual(payload["status"], "awaiting_finger")

    def test_preserves_nonzero_abnormal_readings(self) -> None:
        abnormal = frame(
            heart_rate=29,
            spo2=69,
            systolic=55,
            diastolic=28,
            respiratory_rate=4,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            fixture.write_bytes(abnormal)
            completed = subprocess.run(
                [
                    "perl",
                    str(PARSER),
                    "--input-file",
                    str(fixture),
                    "--stable-frames",
                    "1",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(payload["finger_detected"])
        self.assertEqual(payload["heart_rate_bpm"], 29)
        self.assertEqual(payload["spo2_percent"], 69)
        self.assertEqual(payload["systolic_pressure"], 55)
        self.assertEqual(payload["diastolic_pressure"], 28)
        self.assertEqual(payload["respiratory_rate"], 4)

    def test_rejects_a_concurrent_uart_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            lock_path = temp / "vitals.lock"
            fixture.write_bytes(
                frame(heart_rate=74, spo2=98, systolic=119, diastolic=78, respiratory_rate=16)
            )
            with lock_path.open("w", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                env = os.environ.copy()
                env["VITALS_UART_LOCK_FILE"] = str(lock_path)
                completed = subprocess.run(
                    [
                        "perl",
                        str(PARSER),
                        "--input-file",
                        str(fixture),
                        "--output",
                        str(output),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                )

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("already in progress", payload["error"])

    def test_aggregates_sparse_reference_metrics_across_recent_frames(self) -> None:
        core = frame(
            heart_rate=70,
            spo2=98,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
            hrv_sdnn=0,
            hrv_rmssd=0,
            body_temperature=(36, 11),
            ambient_temperature=(26, 8),
        )
        pressure = frame(
            heart_rate=72,
            spo2=98,
            systolic=118,
            diastolic=76,
            respiratory_rate=16,
            hrv_sdnn=0,
            hrv_rmssd=0,
            body_temperature=(36, 12),
            ambient_temperature=(26, 9),
        )
        hrv = frame(
            heart_rate=71,
            spo2=99,
            systolic=0,
            diastolic=0,
            respiratory_rate=15,
            hrv_sdnn=42,
            hrv_rmssd=30,
            body_temperature=(36, 13),
            ambient_temperature=(26, 10),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            fixture.write_bytes(core + pressure + hrv)
            completed = subprocess.run(
                [
                    "perl",
                    str(PARSER),
                    "--input-file",
                    str(fixture),
                    "--stable-frames",
                    "3",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["heart_rate_bpm"], 71)
        self.assertEqual(payload["spo2_percent"], 98)
        self.assertEqual(payload["systolic_pressure"], 118)
        self.assertEqual(payload["diastolic_pressure"], 76)
        self.assertEqual(payload["respiratory_rate"], 16)
        self.assertEqual(payload["hrv_sdnn"], 42)
        self.assertEqual(payload["hrv_rmssd"], 30)
        self.assertEqual(payload["body_temperature_c"], 36.12)
        self.assertEqual(payload["ambient_temperature_c"], 26.09)
        self.assertTrue(payload["reference_ready"])

    def test_core_readings_finish_without_waiting_for_optional_reference_metrics(self) -> None:
        core = frame(
            heart_rate=73,
            spo2=98,
            systolic=0,
            diastolic=0,
            respiratory_rate=0,
            hrv_sdnn=0,
            hrv_rmssd=0,
        )
        trailing = frame(
            heart_rate=75,
            spo2=99,
            systolic=120,
            diastolic=79,
            respiratory_rate=16,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = temp / "uart.bin"
            output = temp / "vitals.json"
            fixture.write_bytes(core + core + core + trailing + trailing)
            completed = subprocess.run(
                [
                    "perl",
                    str(PARSER),
                    "--input-file",
                    str(fixture),
                    "--chunk-size",
                    "24",
                    "--stable-frames",
                    "3",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["valid_frame_count"], 3)
        self.assertEqual(payload["heart_rate_bpm"], 73)
        self.assertEqual(payload["spo2_percent"], 98)
        self.assertFalse(payload["reference_ready"])


if __name__ == "__main__":
    unittest.main()
