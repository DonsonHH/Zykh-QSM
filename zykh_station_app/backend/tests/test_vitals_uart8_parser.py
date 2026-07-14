from __future__ import annotations

import json
import os
import subprocess
import tempfile
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
    body_temperature: tuple[int, int] = (0, 0),
    ambient_temperature: tuple[int, int] = (26, 37),
) -> bytes:
    return bytes(
        [
            0xFF,
            0x01,
            heart_rate,
            spo2,
            5,
            systolic,
            diastolic,
            respiratory_rate,
            22,
            81,
            43,
            31,
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
        self.assertEqual(payload["body_temperature_raw"], {"integer": 36, "decimal": 55})
        self.assertEqual(payload["valid_frame_count"], 2)

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


if __name__ == "__main__":
    unittest.main()
