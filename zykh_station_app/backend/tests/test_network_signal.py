from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.network_service import NetworkService  # noqa: E402


class NetworkSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        NetworkService._sim_signal_cache = None

    def test_wifi_dbm_maps_to_four_bar_scale(self) -> None:
        self.assertEqual(NetworkService.signal_metrics(-45, "wifi"), {"dbm": -45, "percent": 100, "bars": 4, "level": "excellent"})
        self.assertEqual(NetworkService.signal_metrics(-67, "wifi")["bars"], 3)
        self.assertEqual(NetworkService.signal_metrics(-76, "wifi")["bars"], 2)
        self.assertEqual(NetworkService.signal_metrics(-84, "wifi")["bars"], 1)
        self.assertEqual(NetworkService.signal_metrics(None, "wifi")["bars"], 0)

    def test_sim_csq_maps_to_real_dbm_and_bars(self) -> None:
        metrics = NetworkService.sim_signal_metrics(29)

        self.assertEqual(metrics["csq"], 29)
        self.assertEqual(metrics["dbm"], -55)
        self.assertEqual(metrics["bars"], 4)
        self.assertEqual(NetworkService.sim_signal_metrics(99)["bars"], 0)

    def test_connected_sim_keeps_recent_valid_sample_when_modem_returns_unknown(self) -> None:
        live = NetworkService.stable_sim_signal_metrics(29, connected=True)
        cached = NetworkService.stable_sim_signal_metrics(99, connected=True)

        self.assertEqual(live["sample"], "live")
        self.assertEqual(cached["sample"], "cached")
        self.assertEqual(cached["csq"], 29)
        self.assertEqual(cached["bars"], 4)

    def test_disconnected_sim_does_not_reuse_cached_signal(self) -> None:
        NetworkService.stable_sim_signal_metrics(29, connected=True)
        unavailable = NetworkService.stable_sim_signal_metrics(99, connected=False)

        self.assertEqual(unavailable["sample"], "unavailable")
        self.assertEqual(unavailable["bars"], 0)


if __name__ == "__main__":
    unittest.main()
