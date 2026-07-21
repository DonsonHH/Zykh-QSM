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

    def test_qsm_modem_is_reported_connected_without_host_tether(self) -> None:
        service = NetworkService()
        with (
            patch("app.services.network_service.db.get_setting", return_value="sim"),
            patch("app.services.network_service.db.set_setting"),
            patch.object(service, "_interface_ipv4", return_value=""),
            patch.object(service, "_default_interface", return_value=""),
            patch.object(service, "_wifi_status", return_value={
                "wifi_connected": False,
                "wifi_signal": "none",
                "wifi_ssid": "",
                "wifi_interface": "",
                "wifi_signal_dbm": None,
                "wifi_signal_percent": 0,
                "wifi_signal_bars": 0,
                "wifi_signal_level": "none",
            }),
            patch.object(service, "_host_tether_ready", return_value=False),
            patch.object(service, "_qsm_network_status", return_value={
                "ok": True,
                "connected": True,
                "sim_present": True,
                "signal_csq": 27,
            }),
            patch.object(service, "_sim_identity", return_value={
                "sim_operator": "中国移动",
                "sim_operator_code": "46000",
                "sim_phone_number": "",
            }),
            patch("app.services.network_service.LocalAiClient.status", return_value={"ready": False}),
        ):
            status = service.status()

        self.assertEqual(status["transport"], "local")
        self.assertTrue(status["sim_connected"])
        self.assertTrue(status["qsm_sim_connected"])
        self.assertFalse(status["host_tether_ready"])
        self.assertIn("主机备用通道未就绪", status["warnings"][0])

    def test_wifi_status_keeps_qsm_sim_connection_visible_without_host_tether(self) -> None:
        service = NetworkService()
        with (
            patch("app.services.network_service.db.get_setting", return_value="sim"),
            patch("app.services.network_service.db.set_setting"),
            patch.object(service, "_interface_ipv4", return_value=""),
            patch.object(service, "_default_interface", return_value="wlan0"),
            patch.object(service, "_wifi_status", return_value={
                "wifi_connected": True,
                "wifi_signal": "good",
                "wifi_ssid": "station-wifi",
                "wifi_interface": "wlan0",
                "wifi_signal_dbm": -48,
                "wifi_signal_percent": 96,
                "wifi_signal_bars": 4,
                "wifi_signal_level": "excellent",
            }),
            patch.object(service, "_host_tether_ready", return_value=False),
            patch.object(service, "_qsm_network_status", return_value={
                "ok": True,
                "connected": True,
                "sim_present": True,
                "ip": "10.96.52.118",
                "signal": "good",
                "signal_csq": 26,
            }),
            patch.object(service, "_sim_identity", return_value={
                "sim_operator": "中国移动",
                "sim_operator_code": "46000",
                "sim_phone_number": "",
            }),
            patch("app.services.network_service.LocalAiClient.status", return_value={"ready": True}),
        ):
            status = service.status()

        self.assertEqual(status["transport"], "wifi")
        self.assertTrue(status["wifi_connected"])
        self.assertTrue(status["sim_connected"])
        self.assertTrue(status["qsm_sim_connected"])
        self.assertFalse(status["host_tether_ready"])

    def test_local_display_mode_hides_network_but_keeps_cloud_inquiry_route(self) -> None:
        service = NetworkService()
        with (
            patch("app.services.network_service.db.get_setting", return_value="local"),
            patch.object(service, "_interface_ipv4", return_value=""),
            patch.object(service, "_default_interface", return_value=""),
            patch.object(service, "_wifi_status", return_value={
                "wifi_connected": False,
                "wifi_signal": "none",
                "wifi_ssid": "",
                "wifi_interface": "",
                "wifi_signal_dbm": None,
                "wifi_signal_percent": 0,
                "wifi_signal_bars": 0,
                "wifi_signal_level": "none",
            }),
            patch.object(service, "_host_tether_ready", return_value=False),
            patch.object(service, "_qsm_network_status", return_value={}),
            patch.object(service, "_sim_identity", return_value={
                "sim_operator": "",
                "sim_operator_code": "",
                "sim_phone_number": "",
            }),
            patch("app.services.network_service.LocalAiClient.status", return_value={
                "ready": False,
                "status": "unavailable",
                "model": "board-model",
            }),
        ):
            status = service.status()

        self.assertEqual(status["ai_mode"], "cloud")
        self.assertEqual(status["label"], "本地模式")
        self.assertTrue(status["local_ai"]["ready"])
        self.assertFalse(status["local_ai"]["runtime_ready"])
        self.assertNotIn("本地问询服务尚未就绪。", status["warnings"])


if __name__ == "__main__":
    unittest.main()
