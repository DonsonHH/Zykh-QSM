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
        self.assertGreaterEqual(int(match.group(1)), 18)

    def test_measurements_require_fresh_stable_frames_after_preheat(self) -> None:
        gateway = GATEWAY.read_text(encoding="utf-8")
        reader = READER.read_text(encoding="utf-8")
        self.assertIn("/api/vitals/prepare", gateway)
        self.assertRegex(gateway, r"--stable-frames['\s,]+3")
        self.assertIn("--prewarmed", gateway)
        self.assertIn("minimum_measurement_seconds", reader)
        self.assertIn("minimum_contact_seconds", reader)


if __name__ == "__main__":
    unittest.main()
