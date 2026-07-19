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

    def test_warm_measurements_can_finish_as_soon_as_frames_are_stable(self) -> None:
        source = READER.read_text(encoding="utf-8")
        self.assertIn("last if measurement_window_ready", source)
        self.assertIn("stabilization_grace", source)


if __name__ == "__main__":
    unittest.main()
