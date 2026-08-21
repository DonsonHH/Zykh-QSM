from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.device_check_service import DeviceCheckService  # noqa: E402


class FakeQsm:
    def __init__(self, cabinet_light=None) -> None:
        self.cabinet_light = cabinet_light or {"ok": True, "status": "off"}

    def get_qsm_status(self):
        return SimpleNamespace(
            mode="real",
            connected=True,
            base_url="http://127.0.0.1:18080",
        )

    def read_vitals(self):
        return {"source": "real"}

    def cabinet_light_status(self):
        return self.cabinet_light


class FakeCamera:
    def capabilities(self):
        return "available"


class FakeFingerprint:
    def status(self):
        return SimpleNamespace(ok=True, status="available", bound_users=2)


class FakeSpeech:
    def __init__(self, available: bool) -> None:
        self.available = available

    def status(self):
        return {
            "offline_available": self.available,
            "offline": {"engine": "sherpa-onnx", "model": "xiao-ya"},
        }


class DeviceCheckServiceTest(unittest.TestCase):
    def _check(self, available: bool, cabinet_light=None):
        with patch("app.services.device_check_service.real_dispense_enabled", return_value=True):
            return DeviceCheckService(
                qsm_client=FakeQsm(cabinet_light),
                qsm_camera=FakeCamera(),
                fingerprint=FakeFingerprint(),
                speech=FakeSpeech(available),
            ).check()

    def test_system_check_reports_qsm_offline_voice_without_exposing_a_local_llm(self) -> None:
        result = self._check(True)

        self.assertTrue(result.offline_tts_ok)
        self.assertEqual(result.offline_tts_engine, "sherpa-onnx")
        self.assertNotIn("离线问询", " ".join(result.warnings + result.recommendations))

    def test_missing_qsm_voice_has_a_voice_specific_recommendation(self) -> None:
        result = self._check(False)

        self.assertFalse(result.offline_tts_ok)
        self.assertIn("本地语音暂未就绪。", result.warnings)
        self.assertTrue(any("deploy_offline_tts.sh" in item for item in result.recommendations))

    def test_system_check_requires_a_confirmed_off_cabinet_status(self) -> None:
        result = self._check(
            True,
            {"ok": False, "status": "unknown", "detail": "serial unavailable"},
        )

        self.assertFalse(result.cabinet_light_ok)
        self.assertEqual(result.cabinet_light_status, "unknown")
        self.assertIn("分类柜控制器状态暂不可用。", result.warnings)

    def test_system_check_warns_when_a_cabinet_light_is_still_on(self) -> None:
        result = self._check(
            True,
            {"ok": True, "status": "cabinet_2", "cabinet_id": 2},
        )

        self.assertFalse(result.cabinet_light_ok)
        self.assertEqual(result.cabinet_light_cabinet_id, 2)
        self.assertIn("2号柜指示灯仍亮着。", result.warnings)


if __name__ == "__main__":
    unittest.main()
