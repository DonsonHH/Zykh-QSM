from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.schemas.settings import BasicSettingsUpdateRequest  # noqa: E402
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
            patch("app.services.settings_service.NetworkService.status", return_value={"wifi_ssid": "Station", "sim_connected": True}),
        ):
            result = service.get()

        self.assertEqual(result.settings.speaker_volume, 180)
        self.assertEqual(result.settings.microphone_volume, 64)
        self.assertEqual(result.settings.display_brightness, 72)
        self.assertEqual(result.settings.idle_timeout_seconds, 180)
        self.assertEqual(result.settings.wifi_ssid, "Station")

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
            patch.object(service, "_set_host_speaker_volume") as speaker,
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


if __name__ == "__main__":
    unittest.main()
