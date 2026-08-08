from __future__ import annotations

import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.speech_service import SpeechService  # noqa: E402


class FakeQsmClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None, float | None, str]] = []

    def audio_speak(self, text, volume=None, speed=None, tts_mode="auto"):
        self.calls.append((text, volume, speed, tts_mode))
        return {
            "ok": True,
            "mode": "offline-sherpa-onnx",
            "offline": True,
            "detail": "ok",
        }

    def audio_status(self):
        return {
            "ok": True,
            "offline_available": True,
            "offline": {
                "available": True,
                "engine": "sherpa-onnx",
                "model": "vits-piper-zh_CN-xiao_ya-medium-int8",
            },
        }


class FakeRealtimeTts:
    def __init__(self, _client, *, ok=True) -> None:
        self.ok = ok
        self.calls = []

    async def speak(self, text, api_key, *, volume=None, speed=None):
        self.calls.append((text, api_key, volume, speed))
        if not self.ok:
            return {"ok": False, "error_message": "cloud unavailable"}
        return {"ok": True, "mode": "qwen-realtime-pcm", "offline": False}


class SerialProbeQsmClient(FakeQsmClient):
    def __init__(self) -> None:
        super().__init__()
        self.guard = threading.Lock()
        self.active = 0
        self.max_active = 0

    def audio_speak(self, text, volume=None, speed=None, tts_mode="auto"):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.04)
            return super().audio_speak(text, volume, speed, tts_mode)
        finally:
            with self.guard:
                self.active -= 1


class SpeechServiceTest(unittest.TestCase):
    def test_local_presentation_uses_the_qsm_offline_voice(self) -> None:
        qsm = FakeQsmClient()
        service = SpeechService(qsm)
        with patch("app.services.speech_service.db.get_setting", return_value="local"):
            result = asyncio.run(service.speak("离线播报", volume=230, speed=1.2))

        self.assertEqual(qsm.calls, [("离线播报", 230, 1.2, "offline")])
        self.assertTrue(result["offline"])

    def test_online_presentation_uses_cloud_voice(self) -> None:
        qsm = FakeQsmClient()
        realtime = FakeRealtimeTts(qsm)
        service = SpeechService(qsm, realtime_tts=realtime, api_key_reader=lambda: "private")
        with patch("app.services.speech_service.db.get_setting", return_value="sim"):
            result = asyncio.run(service.speak("联网播报", volume=230))

        self.assertEqual(realtime.calls[0][0], "联网播报")
        self.assertEqual(qsm.calls, [])
        self.assertFalse(result["offline"])

    def test_cloud_voice_failure_falls_back_to_the_qsm_voice(self) -> None:
        qsm = FakeQsmClient()
        realtime = FakeRealtimeTts(qsm, ok=False)
        service = SpeechService(qsm, realtime_tts=realtime, api_key_reader=lambda: "private")
        with patch("app.services.speech_service.db.get_setting", return_value="sim"):
            result = asyncio.run(service.speak("回退播报"))

        self.assertEqual(qsm.calls[0][3], "offline")
        self.assertEqual(result["fallback_reason"], "cloud unavailable")

    def test_status_reports_the_qsm_as_offline_voice_owner(self) -> None:
        service = SpeechService(FakeQsmClient())
        with patch("app.services.speech_service.db.get_setting", return_value="local"):
            status = service.status()

        self.assertEqual(status["tts_owner"], "qsm")
        self.assertTrue(status["offline_available"])
        self.assertEqual(status["requested_mode"], "offline")

    def test_async_and_sync_entry_points_share_one_serial_playback_queue(self) -> None:
        qsm = SerialProbeQsmClient()
        service = SpeechService(qsm)
        sync_done = threading.Event()

        def run_sync_entry() -> None:
            try:
                service.speak_sync("同步入口")
            finally:
                sync_done.set()

        async def exercise() -> None:
            worker = threading.Thread(target=run_sync_entry, daemon=True)
            worker.start()
            await service.speak("异步入口")
            while not sync_done.is_set():
                await asyncio.sleep(0.01)
            worker.join(timeout=1)

        with patch("app.services.speech_service.db.get_setting", return_value="local"):
            asyncio.run(exercise())

        self.assertEqual(qsm.max_active, 1)
        self.assertCountEqual(
            [call[0] for call in qsm.calls],
            ["异步入口", "同步入口"],
        )


if __name__ == "__main__":
    unittest.main()
