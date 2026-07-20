from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class LocalTtsGatewaySourceTest(unittest.TestCase):
    def test_offline_tts_uses_parallel_inference_and_short_silence(self) -> None:
        source = (ROOT / "qsm_gateway" / "local_tts_server.cpp").read_text(encoding="utf-8")
        threads = re.search(r"config\.model\.num_threads\s*=\s*(\d+)", source)
        silence = re.findall(r"silence_scale\s*=\s*([0-9.]+)f", source)

        self.assertIsNotNone(threads)
        self.assertGreaterEqual(int(threads.group(1)), 4)
        self.assertTrue(silence)
        self.assertTrue(all(float(value) <= 0.05 for value in silence))
        self.assertIn("max_callback_gap_ms", source)
        self.assertIn("std::thread playback_thread(PlaybackWorker", source)
        self.assertIn("pending.push_back", source)
        self.assertIn("generation_done = true", source)
        self.assertIn("prebuffer_samples", source)
        self.assertIn("underflow_count", source)

    def test_deploy_forces_the_running_daemon_to_restart(self) -> None:
        deploy = (ROOT / "scripts" / "deploy_local_tts_server.sh").read_text(encoding="utf-8")
        startup = (ROOT / "qsm_gateway" / "start_local_tts_server.sh").read_text(encoding="utf-8")

        self.assertIn("start_local_tts_server.sh restart", deploy)
        self.assertIn("-static-libstdc++", deploy)
        self.assertIn("-pthread", deploy)
        self.assertIn('ACTION="${1:-start}"', startup)
        self.assertIn('if [ "$ACTION" = "restart" ]', startup)


if __name__ == "__main__":
    unittest.main()
