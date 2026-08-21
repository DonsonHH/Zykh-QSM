from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.network_service import NetworkService  # noqa: E402
from app.config import settings  # noqa: E402


class NetworkSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        NetworkService._sim_signal_cache = None
        NetworkService._qsm_network_cache = None
        self.physical_network_settings = patch(
            "app.services.network_service.settings",
            replace(settings, network_demo_simulate=False),
        )
        self.physical_network_settings.start()

    def tearDown(self) -> None:
        self.physical_network_settings.stop()

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

    def test_simulated_4g_status_reads_host_wifi_without_touching_4g_hardware(self) -> None:
        service = NetworkService()
        host_wifi = {
            "wifi_connected": True,
            "wifi_signal": "good",
            "wifi_ssid": "Station",
            "wifi_interface": "wlan0",
            "wifi_signal_dbm": -63,
            "wifi_signal_percent": 74,
            "wifi_signal_bars": 3,
            "wifi_signal_level": "good",
        }
        with (
            patch(
                "app.services.network_service.settings",
                replace(settings, network_demo_simulate=True),
            ),
            patch("app.services.network_service.db.get_setting", side_effect=lambda _key, default="": default),
            patch.object(service, "_interface_ipv4") as interface_ipv4,
            patch.object(service, "_default_interface", return_value="wlan0") as default_interface,
            patch.object(service, "_wifi_status", return_value=host_wifi) as wifi_status,
            patch.object(service, "_ping_target") as ping_target,
            patch.object(service, "_host_tether_ready") as host_tether_ready,
            patch.object(service, "_qsm_network_status") as qsm_network_status,
            patch.object(service, "_sim_identity") as sim_identity,
            patch.object(service, "_read_qsm_sim_phone_number") as adb_phone_number,
            patch("app.services.network_service.QsmClient.get_network_status") as qsm_probe,
            patch("app.services.network_service.QsmClient.start_4g_network") as qsm_start,
            patch.object(service, "_prepare_host_tether") as prepare_tether,
        ):
            status = service.status()

        self.assertEqual(status["mode"], "sim")
        self.assertEqual(status["transport"], "sim")
        self.assertEqual(status["status"], "good")
        self.assertEqual(status["signal"], "good")
        self.assertEqual(status["sim_signal"], "good")
        self.assertIsNone(status["sim_signal_csq"])
        self.assertIsNone(status["sim_signal_dbm"])
        self.assertEqual(status["sim_signal_percent"], 0)
        self.assertEqual(status["sim_signal_bars"], 3)
        self.assertEqual(status["sim_signal_level"], "good")
        self.assertTrue(status["sim_present"])
        self.assertTrue(status["sim_connected"])
        self.assertTrue(status["simulated"])
        self.assertFalse(status["qsm_sim_connected"])
        self.assertEqual(status["source"], "simulation")
        self.assertEqual(status["warnings"], [])
        self.assertTrue(status["wifi_connected"])
        self.assertEqual(status["wifi_ssid"], "Station")
        self.assertEqual(status["wifi_signal_bars"], 3)
        interface_ipv4.assert_not_called()
        default_interface.assert_called_once_with()
        wifi_status.assert_called_once_with("wlan0")
        ping_target.assert_not_called()
        host_tether_ready.assert_not_called()
        qsm_network_status.assert_not_called()
        sim_identity.assert_not_called()
        adb_phone_number.assert_not_called()
        qsm_probe.assert_not_called()
        qsm_start.assert_not_called()
        prepare_tether.assert_not_called()

    def test_simulated_4g_start_is_a_hardware_free_noop(self) -> None:
        service = NetworkService()
        host_wifi = {
            "wifi_connected": True,
            "wifi_signal": "good",
            "wifi_ssid": "Station",
            "wifi_interface": "wlan0",
            "wifi_signal_dbm": -63,
            "wifi_signal_percent": 74,
            "wifi_signal_bars": 3,
            "wifi_signal_level": "good",
        }
        with (
            patch(
                "app.services.network_service.settings",
                replace(settings, network_demo_simulate=True),
            ),
            patch("app.services.network_service.db.get_setting", side_effect=lambda _key, default="": default),
            patch.object(service, "_default_interface", return_value="wlan0") as default_interface,
            patch.object(service, "_wifi_status", return_value=host_wifi) as wifi_status,
            patch("app.services.network_service.QsmClient.start_4g_network") as start_4g,
            patch.object(service, "_prepare_host_tether") as prepare_tether,
        ):
            result = service.start_4g()

        self.assertTrue(result["ok"])
        self.assertTrue(result["network"]["simulated"])
        self.assertTrue(result["network"]["wifi_connected"])
        default_interface.assert_called_once_with()
        wifi_status.assert_called_once_with("wlan0")
        start_4g.assert_not_called()
        prepare_tether.assert_not_called()

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
        ):
            status = service.status()

        self.assertEqual(status["transport"], "wifi")
        self.assertTrue(status["wifi_connected"])
        self.assertTrue(status["sim_connected"])
        self.assertTrue(status["qsm_sim_connected"])
        self.assertFalse(status["host_tether_ready"])

    def test_local_display_mode_only_changes_presentation_and_sync(self) -> None:
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
        ):
            status = service.status()

        self.assertEqual(status["ai_mode"], "cloud")
        self.assertEqual(status["label"], "本地模式")
        self.assertEqual(status["display_mode"], "local")
        self.assertFalse(status["realtime_sync_enabled"])

    def test_local_display_mode_keeps_physical_wifi_status(self) -> None:
        service = NetworkService()
        with (
            patch("app.services.network_service.db.get_setting", return_value="local"),
            patch.object(service, "_interface_ipv4", return_value=""),
            patch.object(service, "_default_interface", return_value="wlan0"),
            patch.object(service, "_wifi_status", return_value={
                "wifi_connected": True,
                "wifi_signal": "good",
                "wifi_ssid": "Station",
                "wifi_interface": "wlan0",
                "wifi_signal_dbm": -48,
                "wifi_signal_percent": 86,
                "wifi_signal_bars": 4,
                "wifi_signal_level": "excellent",
            }),
            patch.object(service, "_host_tether_ready", return_value=False),
            patch.object(service, "_qsm_network_status", return_value={}),
            patch.object(service, "_sim_identity", return_value={
                "sim_operator": "",
                "sim_operator_code": "",
                "sim_phone_number": "",
            }),
        ):
            status = service.status()

        self.assertEqual(status["transport"], "wifi")
        self.assertEqual(status["display_mode"], "local")
        self.assertFalse(status["realtime_sync_enabled"])


if __name__ == "__main__":
    unittest.main()
