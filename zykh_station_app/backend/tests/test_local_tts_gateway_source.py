from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class HostTtsRoutingSourceTest(unittest.TestCase):
    def test_host_service_owns_model_and_qsm_only_receives_pcm(self) -> None:
        source = (ROOT / "backend" / "app" / "services" / "host_offline_tts.py").read_text(encoding="utf-8")
        self.assertIn("sherpa_onnx.OfflineTts", source)
        self.assertIn("audio_stream_start", source)
        self.assertIn("host-offline-sherpa-onnx-pcm", source)
        self.assertIn("主机离线语音已发送到外设喇叭", source)

    def test_startup_scripts_do_not_start_board_tts(self) -> None:
        station = (ROOT / "qsm_gateway" / "start_station_gateway.sh").read_text(encoding="utf-8")
        forward = (ROOT / "scripts" / "adb_forward.sh").read_text(encoding="utf-8")
        ensure = (ROOT / "scripts" / "ensure_qsm_gateway.sh").read_text(encoding="utf-8")
        for source in (station, forward, ensure):
            self.assertNotIn("start_local_tts_server.sh", source)

    def test_old_deploy_entry_points_redirect_to_host(self) -> None:
        for name in ("deploy_offline_tts.sh", "deploy_local_tts_server.sh"):
            source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("deploy_host_offline_tts.sh", source)


if __name__ == "__main__":
    unittest.main()
