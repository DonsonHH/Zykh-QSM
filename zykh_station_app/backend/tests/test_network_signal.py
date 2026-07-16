from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.network_service import NetworkService  # noqa: E402


class NetworkSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        NetworkService._sim_signal_cache = None
        NetworkService._qsm_network_cache = None

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

    def test_sim_identity_maps_operator_and_uses_real_module_number(self) -> None:
        with (
            patch("app.services.network_service.db.get_setting", return_value=""),
            patch("app.services.network_service.db.set_setting"),
            patch.object(NetworkService, "_read_qsm_sim_phone_number", return_value="+8613800138000"),
        ):
            identity = NetworkService._sim_identity(
                {"sim_present": True},
                {"operator": "46000"},
            )

        self.assertEqual(identity["sim_operator"], "中国移动")
        self.assertEqual(identity["sim_phone_number"], "+8613800138000")

    def test_qsm_network_probe_is_shared_during_short_refresh_burst(self) -> None:
        with patch(
            "app.services.network_service.QsmClient.get_network_status",
            return_value={"ok": True, "connected": True, "signal_csq": 28},
        ) as probe:
            first = NetworkService._qsm_network_status()
            second = NetworkService._qsm_network_status()

        self.assertEqual(first, second)
        probe.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
