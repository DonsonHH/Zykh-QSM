from __future__ import annotations

import re
import unittest
from pathlib import Path


GATEWAY = Path(__file__).resolve().parents[1] / "vitals_gateway.pl"
READER = Path(__file__).resolve().parents[1] / "read_vitals_uart8.pl"


class VitalsGatewayContractTest(unittest.TestCase):
    def test_cold_start_allows_sensor_algorithm_to_initialize(self) -> None:
        source = GATEWAY.read_text(encoding="utf-8")
        match = re.search(r"QSM_VITALS_MEASURE_TIMEOUT\}\s*\|\|\s*(\d+)", source)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), 18)

    def test_phase3_keeps_timing_windows_and_uart_protocol_unchanged(self) -> None:
        gateway = GATEWAY.read_text(encoding="utf-8")
        reader = READER.read_text(encoding="utf-8")

        self.assertRegex(
            reader,
            r"VITALS_UART_STABILIZATION_GRACE_SECONDS\},\s*12\)",
        )
        self.assertRegex(gateway, r"QSM_VITALS_SPO2_GRACE_SECONDS\}\s*\|\|\s*8")
        self.assertRegex(reader, r"VITALS_UART_SPO2_GRACE_SECONDS\},\s*8\)")
        self.assertIn("pack('C', 0x24)", reader)
        self.assertIn("pack('C', 0x2A)", reader)
        self.assertIn("while (length($$buffer_ref) >= 24)", reader)
        self.assertIn("substr($$buffer_ref, 0, 24)", reader)
        self.assertIn("$bytes[0] == 0xFF", reader)
        self.assertIn("$bytes[1] == 0x01", reader)
        self.assertIn("$bytes[23] == 0xF1", reader)

    def test_measurements_require_fresh_stable_frames_after_preheat(self) -> None:
        gateway = GATEWAY.read_text(encoding="utf-8")
        reader = READER.read_text(encoding="utf-8")
        self.assertIn("/api/vitals/prepare", gateway)
        self.assertRegex(gateway, r"QSM_VITALS_STABLE_FRAMES\}\s*\|\|\s*2")
        self.assertRegex(gateway, r"--stable-frames['\s,]+\$STABLE_FRAMES")
        self.assertRegex(gateway, r"QSM_VITALS_INITIAL_STABILIZATION_SECONDS\}\s*\|\|\s*8")
        self.assertIn("prewarm_age", gateway)
        self.assertIn("minimum_measurement_seconds", gateway)
        self.assertIn("--prewarmed", gateway)
        self.assertIn("minimum_measurement_seconds", reader)
        self.assertIn("minimum_contact_seconds", reader)
        self.assertIn("communication_status", reader)
        self.assertIn("start_recovery_seconds", reader)
        self.assertIn("prewarmed_no_frames", reader)
        self.assertIn("prewarmed_stalled_frames", reader)
        self.assertIn("start_recovery_mode", gateway)

    def test_missing_spo2_demo_fallback_is_explicitly_marked(self) -> None:
        gateway = GATEWAY.read_text(encoding="utf-8")
        self.assertIn("QSM_VITALS_DEMO_SPO2_FALLBACK", gateway)
        self.assertIn("spo2_demo_fallback", gateway)
        self.assertIn("spo2_source", gateway)


if __name__ == "__main__":
    unittest.main()
