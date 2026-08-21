from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.schemas.settings import BasicSettingsUpdateRequest  # noqa: E402
from app.services.network_service import NetworkService  # noqa: E402
from app.services.settings_service import SettingsService  # noqa: E402


class SettingsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "settings.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_get_returns_persisted_user_settings(self) -> None:
        db.set_setting("speaker_volume", "180")
        db.set_setting("microphone_volume", "64")
        db.set_setting("display_brightness", "72")
        db.set_setting("idle_timeout_seconds", "180")
        service = SettingsService()

        with (
            patch.object(service, "_wifi_radio_enabled", return_value=True),
            patch.object(service, "_microphone_available", return_value=True),
            patch(
                "app.services.settings_service.NetworkService.status",
                return_value={
                    "wifi_ssid": "Station",
                    "sim_connected": True,
                    "sim_operator": "中国移动",
                    "sim_operator_code": "46000",
                    "sim_phone_number": "13800138000",
                },
            ),
        ):
            result = service.get()

        self.assertEqual(result.settings.speaker_volume, 180)
        self.assertEqual(result.settings.microphone_volume, 64)
        self.assertEqual(result.settings.display_brightness, 72)
        self.assertEqual(result.settings.idle_timeout_seconds, 180)
        self.assertEqual(result.settings.wifi_ssid, "Station")
        self.assertEqual(result.settings.sim_operator, "中国移动")
        self.assertEqual(result.settings.sim_phone_number, "13800138000")

    def test_get_exposes_simulated_network_provenance_to_admin_clients(self) -> None:
        service = SettingsService()

        with (
            patch.object(service, "_wifi_radio_enabled", return_value=True),
            patch.object(service, "_microphone_available", return_value=True),
            patch(
                "app.services.settings_service.NetworkService.status",
                return_value={"simulated": True, "source": "simulation"},
            ),
        ):
            payload = service.get().model_dump()["settings"]

        self.assertIs(payload["network_simulated"], True)
        self.assertEqual(payload["network_source"], "simulation")

    def test_update_saves_values_and_invokes_fixed_controls(self) -> None:
        service = SettingsService()
        request = BasicSettingsUpdateRequest(
            wifi_enabled=False,
            sim_enabled=False,
            network_mode="local",
            speaker_volume=150,
            microphone_volume=55,
            display_brightness=60,
            idle_timeout_seconds=300,
        )
        with (
            patch.object(service, "_set_wifi", return_value="") as wifi,
            patch.object(service, "_set_sim", return_value="") as sim,
            patch.object(service, "_set_brightness", return_value="") as brightness,
            patch.object(service, "_set_host_speaker_volume", return_value="") as speaker,
            patch.object(service, "_qsm_mic_volume", return_value={"ok": True}),
            patch.object(service, "_wifi_radio_enabled", return_value=False),
            patch.object(service, "_microphone_available", return_value=True),
            patch("app.services.settings_service.NetworkService.set_mode", side_effect=lambda mode: db.set_setting("network_mode", mode)),
            patch("app.services.settings_service.NetworkService.status", return_value={}),
        ):
            result = service.update(request)

        wifi.assert_called_once_with(False)
        sim.assert_called_once_with(False)
        brightness.assert_called_once_with(60)
        speaker.assert_called_once_with(150)
        self.assertEqual(db.get_setting("speaker_volume"), "150")
        self.assertEqual(db.get_setting("idle_timeout_seconds"), "300")
        self.assertEqual(result.settings.network_mode, "local")

    def test_get_migrates_legacy_inaudible_gain_once(self) -> None:
        db.set_setting("speaker_volume", "8")
        service = SettingsService()

        with (
            patch.object(service, "_wifi_radio_enabled", return_value=True),
            patch.object(service, "_microphone_available", return_value=True),
            patch("app.services.settings_service.NetworkService.status", return_value={}),
        ):
            result = service.get()

        self.assertEqual(result.settings.speaker_volume, 180)
        self.assertEqual(db.get_setting("speaker_volume"), "180")
        self.assertEqual(db.get_setting("speaker_volume_scale_version"), "2")

    def test_versioned_invalid_low_gain_is_clamped_without_replaying_migration(self) -> None:
        db.set_setting("speaker_volume", "8")
        db.set_setting("speaker_volume_scale_version", "2")
        service = SettingsService()

        with (
            patch.object(service, "_wifi_radio_enabled", return_value=True),
            patch.object(service, "_microphone_available", return_value=True),
            patch("app.services.settings_service.NetworkService.status", return_value={}),
        ):
            result = service.get()

        self.assertEqual(result.settings.speaker_volume, 128)
        self.assertEqual(db.get_setting("speaker_volume"), "128")

    def test_update_canonicalizes_legacy_gain_before_hardware_and_storage(self) -> None:
        service = SettingsService()
        request = BasicSettingsUpdateRequest(speaker_volume=45)
        with (
            patch.object(service, "_set_host_speaker_volume", return_value="") as speaker,
            patch.object(service, "_wifi_radio_enabled", return_value=True),
            patch.object(service, "_microphone_available", return_value=True),
            patch("app.services.settings_service.NetworkService.status", return_value={}),
        ):
            result = service.update(request)

        speaker.assert_called_once_with(214)
        self.assertEqual(result.settings.speaker_volume, 214)
        self.assertEqual(db.get_setting("speaker_volume"), "214")

    def test_update_reports_host_sink_failure_without_losing_setting(self) -> None:
        service = SettingsService()
        request = BasicSettingsUpdateRequest(speaker_volume=180)
        with (
            patch.object(service, "_set_host_speaker_volume", return_value="外放音量已保存，但本机音频转发暂未就绪。"),
            patch.object(service, "_wifi_radio_enabled", return_value=True),
            patch.object(service, "_microphone_available", return_value=True),
            patch("app.services.settings_service.NetworkService.status", return_value={}),
        ):
            result = service.update(request)

        self.assertEqual(result.settings.speaker_volume, 180)
        self.assertIn("本机音频转发暂未就绪", result.warnings[0])

    def test_host_speaker_uses_same_calibrated_percentage_as_terminal(self) -> None:
        service = SettingsService()
        expected = {
            0: 0,
            128: 1,
            180: 50,
            230: 85,
            255: 100,
        }

        with patch.object(service, "_run") as run:
            for gain in expected:
                service._set_host_speaker_volume(gain)

        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["pactl", "set-sink-volume", "qsm_relay", f"{percent}%"],
                    timeout=3,
                )
                for percent in expected.values()
            ],
        )

    def test_wifi_stays_on_when_sim_backup_cannot_be_prepared(self) -> None:
        service = SettingsService()
        with (
            patch.object(service, "_bool_setting", return_value=True),
            patch("app.services.settings_service.NetworkService.start_4g", return_value={"ok": False, "message": "备用通道失败"}),
            patch.object(service, "_run") as run,
        ):
            warning = service._set_wifi(False)

        self.assertIn("Wi-Fi 保持开启", warning)
        run.assert_not_called()

    def test_wifi_stays_on_when_4g_is_only_simulated(self) -> None:
        service = SettingsService()
        with (
            patch(
                "app.services.settings_service.settings",
                SimpleNamespace(network_demo_simulate=True),
            ),
            patch("app.services.settings_service.NetworkService.start_4g") as start_4g,
            patch.object(service, "_run") as run,
        ):
            warning = service._set_wifi(False)

        self.assertIn("4G 当前为模拟状态", warning)
        self.assertIn("Wi-Fi 保持开启", warning)
        start_4g.assert_not_called()
        run.assert_not_called()

    def test_wifi_can_turn_off_after_sim_backup_is_ready(self) -> None:
        service = SettingsService()
        command_result = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch(
                "app.services.settings_service.settings",
                SimpleNamespace(network_demo_simulate=False),
            ),
            patch.object(service, "_bool_setting", return_value=True),
            patch("app.services.settings_service.NetworkService.start_4g", return_value={"ok": True}),
            patch.object(service, "_run", return_value=command_result) as run,
        ):
            warning = service._set_wifi(False)

        self.assertEqual(warning, "")
        run.assert_called_once_with(["nmcli", "radio", "wifi", "off"])
        self.assertEqual(db.get_setting("wifi_enabled"), "false")

    def test_disabling_sim_stops_physical_transport_even_with_legacy_flag(self) -> None:
        service = SettingsService()
        command_result = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch(
                "app.services.settings_service.settings",
                SimpleNamespace(
                    network_keep_sim_transport_when_hidden=True,
                    network_preferred_mode="sim",
                    network_demo_simulate=False,
                ),
            ),
            patch("app.services.settings_service.NetworkService.disable_host_tether", return_value={"ok": True}) as disable,
            patch.object(service, "_run", return_value=command_result) as run,
        ):
            warning = service._set_sim(False)

        self.assertEqual(warning, "")
        self.assertEqual(db.get_setting("sim_enabled"), "false")
        disable.assert_called_once_with()
        run.assert_called_once()

    def test_simulated_sim_switch_only_persists_state_without_hardware_access(self) -> None:
        service = SettingsService()
        with (
            patch(
                "app.services.settings_service.settings",
                SimpleNamespace(network_demo_simulate=True),
            ),
            patch("app.services.settings_service.NetworkService.start_4g") as start_4g,
            patch("app.services.settings_service.NetworkService.disable_host_tether") as disable_tether,
            patch.object(service, "_run") as run,
        ):
            enabled_warning = service._set_sim(True)
            disabled_warning = service._set_sim(False)

        self.assertEqual(enabled_warning, "")
        self.assertEqual(disabled_warning, "")
        self.assertEqual(db.get_setting("sim_enabled"), "false")
        start_4g.assert_not_called()
        disable_tether.assert_not_called()
        run.assert_not_called()

    def test_wifi_stays_on_when_real_sim_control_is_disabled(self) -> None:
        service = SettingsService()
        db.set_setting("sim_enabled", "false")
        db.set_setting("network_mode", "local")
        command_result = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch(
                "app.services.settings_service.settings",
                SimpleNamespace(
                    network_keep_sim_transport_when_hidden=True,
                    network_preferred_mode="sim",
                    network_demo_simulate=False,
                ),
            ),
            patch(
                "app.services.settings_service.NetworkService.start_4g",
                side_effect=lambda: db.set_setting("network_mode", "sim") or {"ok": True},
            ) as start_4g,
            patch.object(service, "_run", return_value=command_result) as run,
        ):
            warning = service._set_wifi(False)

        self.assertIn("Wi-Fi 保持开启", warning)
        start_4g.assert_not_called()
        run.assert_not_called()
        self.assertEqual(db.get_setting("network_mode"), "local")

    def test_starting_real_data_network_preserves_display_mode(self) -> None:
        db.set_setting("network_mode", "local")
        service = NetworkService()
        with (
            patch(
                "app.services.network_service.settings",
                SimpleNamespace(network_demo_simulate=False),
            ),
            patch("app.services.network_service.QsmClient.start_4g_network", return_value={"ok": True}),
            patch.object(service, "_prepare_host_tether", return_value={"ok": True, "message": "ready"}),
            patch.object(service, "status", return_value={"display_mode": "local"}),
        ):
            result = service.start_4g()

        self.assertTrue(result["ok"])
        self.assertEqual(db.get_setting("network_mode"), "local")


if __name__ == "__main__":
    unittest.main()
