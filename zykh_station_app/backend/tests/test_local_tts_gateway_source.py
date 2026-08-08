from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class QsmTtsRoutingSourceTest(unittest.TestCase):
    def test_board_gateway_keeps_the_offline_tts_route_enabled(self) -> None:
        patch_source = (ROOT / "qsm_gateway" / "patch_station_gateway.pl").read_text(
            encoding="utf-8"
        )

        self.assertIn("ZYKH_STATION_QSM_TTS", patch_source)
        self.assertNotIn("ZYKH_STATION_HOST_TTS_ONLY", patch_source)
        self.assertIn("speak_text($req->{params})", patch_source)

    def test_qsm_client_calls_the_board_speak_route(self) -> None:
        source = (ROOT / "backend" / "app" / "services" / "qsm_client.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("settings.qsm_audio_speak_path", source)
        self.assertIn('payload["tts_mode"]', source)

    def test_public_audio_routes_do_not_fall_back_to_the_retired_host_voice(self) -> None:
        source = (ROOT / "backend" / "app" / "routers" / "audio.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("get_host_offline_tts", source)
        self.assertIn("SpeechService", source)

    def test_qsm_deploy_entry_points_install_the_board_voice_payload(self) -> None:
        for name in ("deploy_offline_tts.sh", "deploy_local_tts_server.sh"):
            source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("deploy_host_offline_tts.sh", source)
        deploy = (ROOT / "scripts" / "deploy_offline_tts.sh").read_text(encoding="utf-8")
        self.assertIn("/userdata/zykh_voice", deploy)
        self.assertIn("offline_tts.sh", deploy)
        self.assertIn("patch_station_gateway.pl", deploy)
        self.assertIn("start_station_gateway.sh", deploy)
        self.assertIn("qsm_gateway/offline_tts.sh", deploy)
        self.assertNotIn("zykh_app/", deploy)

        board_synth = ROOT / "qsm_gateway" / "offline_tts.sh"
        self.assertTrue(board_synth.is_file())
        source = board_synth.read_text(encoding="utf-8")
        self.assertIn("sherpa-onnx-offline-tts", source)
        self.assertIn("test -s \"$OUTPUT_WAV\"", source)


if __name__ == "__main__":
    unittest.main()
