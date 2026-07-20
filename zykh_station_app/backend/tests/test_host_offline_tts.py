from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.host_offline_tts import HostOfflineTts  # noqa: E402


class HostOfflineTtsTest(unittest.TestCase):
    def test_synthesis_returns_little_endian_pcm(self) -> None:
        engine = HostOfflineTts()
        fake_model = SimpleNamespace(
            generate=lambda text, sid=0, speed=1.0: SimpleNamespace(
                samples=[-1.0, -0.25, 0.0, 0.25, 1.0],
                sample_rate=22050,
            )
        )
        with patch.object(engine, "_load_model", return_value=fake_model):
            pcm, sample_rate = engine._synthesize("测试", 1.0)

        self.assertEqual(sample_rate, 22050)
        self.assertEqual(len(pcm), 10)
        self.assertEqual(pcm[:2], b"\x01\x80")
        self.assertEqual(pcm[-2:], b"\xff\x7f")

    def test_status_reports_missing_host_model_without_fake_readiness(self) -> None:
        engine = HostOfflineTts()
        with patch.object(type(engine), "model_root", new_callable=PropertyMock) as model_root:
            model_root.return_value = Path("/tmp/does-not-exist")
            result = engine.status()

        self.assertFalse(result["ready"])
        self.assertTrue(result["missing"])


if __name__ == "__main__":
    unittest.main()
