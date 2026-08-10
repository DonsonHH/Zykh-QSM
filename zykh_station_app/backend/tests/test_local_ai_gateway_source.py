from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class LocalAiGatewaySourceTest(unittest.TestCase):
    def test_kiosk_leaves_the_board_language_model_disabled_by_default(self) -> None:
        launch_source = (ROOT / "scripts" / "launch_kiosk.sh").read_text(encoding="utf-8")
        runtime_source = (ROOT / "qsm_gateway" / "start_local_ai.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('sh "$ROOT_DIR/scripts/stop_qsm_offline_ai.sh"', launch_source)
        self.assertNotIn("KIOSK_OFFLINE_AI", launch_source)
        self.assertNotIn("ensure_qsm_offline_ai.sh", launch_source)
        self.assertNotIn("/api/ai/warm-local", launch_source)
        self.assertIn("--reasoning off", runtime_source)
        self.assertIn("--reasoning-budget 0", runtime_source)
        self.assertNotIn("AI_INQUIRY_REASONING_EFFORT", runtime_source)

    def test_qsm_runtime_uses_bounded_memory_defaults(self) -> None:
        source = (ROOT / "qsm_gateway" / "start_local_ai.sh").read_text(encoding="utf-8")

        self.assertIn('CTX_SIZE="${LOCAL_AI_CTX_SIZE:-1536}"', source)
        self.assertIn('THREADS="${LOCAL_AI_THREADS:-4}"', source)
        self.assertIn('BATCH_SIZE="${LOCAL_AI_BATCH_SIZE:-256}"', source)
        self.assertIn('UBATCH_SIZE="${LOCAL_AI_UBATCH_SIZE:-64}"', source)
        self.assertIn('CACHE_RAM="${LOCAL_AI_CACHE_RAM:-64}"', source)
        self.assertIn('--ctx-size "$CTX_SIZE"', source)
        self.assertIn('--batch-size "$BATCH_SIZE"', source)
        self.assertIn('--ubatch-size "$UBATCH_SIZE"', source)
        self.assertIn('--cache-type-k q8_0', source)
        self.assertIn('--cache-type-v q8_0', source)
        self.assertIn('--cache-ram "$CACHE_RAM"', source)
        self.assertIn('--cache-prompt', source)
        self.assertIn('--offline', source)
        self.assertIn('--no-webui', source)

    def test_cloud_profile_stops_only_the_managed_board_model(self) -> None:
        host_stop = (ROOT / "scripts" / "stop_qsm_offline_ai.sh").read_text(
            encoding="utf-8"
        )
        board_stop = (ROOT / "qsm_gateway" / "stop_local_ai.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("qsm_gateway/stop_local_ai.sh", host_stop)
        self.assertIn("/userdata/zykh_station_app/local-ai", host_stop)
        self.assertIn("adb_run push", host_stop)
        self.assertIn("QSM_LOCAL_AI_ASSET_DIR", host_stop)
        self.assertIn("LOCAL_AI_MODEL_FILE='$MODEL'", host_stop)
        self.assertNotIn("pkill", host_stop)
        self.assertNotIn("killall", host_stop)
        self.assertIn("/proc/$PID/cmdline", board_stop)
        self.assertIn("LOCAL_AI_SERVER", board_stop)
        self.assertNotIn("pkill", board_stop)
        self.assertNotIn("killall", board_stop)

    def test_normal_gateway_scripts_do_not_probe_or_forward_the_legacy_model(self) -> None:
        normal_scripts = (
            ROOT / "scripts" / "ensure_qsm_gateway.sh",
            ROOT / "scripts" / "check_devices.sh",
            ROOT / "scripts" / "adb_forward.sh",
        )

        for path in normal_scripts:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("QSM_LOCAL_AI_FORWARD", source)
                self.assertNotIn("18083", source)
                self.assertNotIn("8083", source)

        ensure_source = normal_scripts[0].read_text(encoding="utf-8")
        self.assertIn("local_asr_ready", ensure_source)
        self.assertIn("tts_ready", ensure_source)
        self.assertIn('curl -fsS --max-time 3 "$QSM_BASE_URL/api/status"', ensure_source)
        self.assertNotIn("/api/audio/stream/stop", ensure_source)
        self.assertIn("/api/audio/status", ensure_source)
        self.assertIn('"offline_available"', ensure_source)

        check_source = normal_scripts[1].read_text(encoding="utf-8")
        self.assertIn("QSM_LOCAL_ASR_FORWARD_HOST_PORT", check_source)
        self.assertIn("QSM_LOCAL_ASR_FORWARD_DEVICE_PORT", check_source)
        self.assertIn('check_tcp "QSM 板端离线语音识别"', check_source)
        self.assertIn("/api/audio/status", check_source)
        self.assertIn('"offline_available"', check_source)


if __name__ == "__main__":
    unittest.main()
