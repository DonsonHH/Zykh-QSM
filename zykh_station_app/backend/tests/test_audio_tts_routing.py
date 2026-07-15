from __future__ import annotations

import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.routers import audio  # noqa: E402
from app.routers.audio import SpeakRequest  # noqa: E402
from app.services.qsm_client import QsmClient  # noqa: E402


class FakeQsmClient:
    def __init__(self) -> None:
        self.speak_calls: list[tuple[str, int | None, float | None, str]] = []

    def audio_stream_stop(self) -> dict[str, object]:
        return {"ok": True}

    def audio_speak(
        self,
        text: str,
        volume: int | None = None,
        speed: float | None = None,
        tts_mode: str = "auto",
    ) -> dict[str, object]:
        self.speak_calls.append((text, volume, speed, tts_mode))
        return {
            "ok": True,
            "mode": "offline-sherpa-onnx" if tts_mode == "offline" else "qwen-tts",
            "offline": tts_mode == "offline",
            "detail": "ok",
        }


class FakeRealtimeTts:
    def __init__(self, _client) -> None:
        self.calls: list[tuple[str, str, int | None, float | None]] = []

    async def speak(self, text, api_key, *, volume=None, speed=None):
        self.calls.append((text, api_key, volume, speed))
        return {
            "ok": True,
            "mode": "qwen-realtime-pcm",
            "offline": False,
            "first_audio_ms": 320,
            "detail": "ok",
        }


class AudioTtsRoutingTest(unittest.TestCase):
    def test_local_network_forces_offline_tts(self) -> None:
        client = FakeQsmClient()
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio.NetworkService, "status", return_value={"mode": "local"}),
            patch.object(audio, "_record"),
        ):
            result = asyncio.run(audio.audio_speak(SpeakRequest(text="请安全用药。", speed=1.2)))

        self.assertEqual(client.speak_calls[0][3], "offline")
        self.assertEqual(result["engine"], "offline-sherpa-onnx")
        self.assertTrue(result["offline"])

    def test_online_network_uses_auto_mode(self) -> None:
        client = FakeQsmClient()
        realtime = FakeRealtimeTts(client)
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio, "QwenRealtimeTts", return_value=realtime),
            patch.object(audio, "_read_api_key", return_value="private"),
            patch.object(audio.NetworkService, "status", return_value={"mode": "wifi"}),
            patch.object(audio, "_record"),
        ):
            result = asyncio.run(audio.audio_speak(SpeakRequest(text="联网播报。")))

        self.assertEqual(client.speak_calls, [])
        self.assertEqual(realtime.calls[0][0], "联网播报。")
        self.assertEqual(result["engine"], "qwen-realtime-pcm")
        self.assertEqual(result["first_audio_ms"], 320)

    def test_local_network_cannot_be_overridden_with_cloud_mode(self) -> None:
        client = FakeQsmClient()
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio.NetworkService, "status", return_value={"mode": "local"}),
            patch.object(audio, "_record"),
        ):
            asyncio.run(audio.audio_speak(SpeakRequest(text="指定云端。", mode="cloud")))

        self.assertEqual(client.speak_calls[0][3], "offline")

    def test_online_request_can_explicitly_select_offline_mode(self) -> None:
        client = FakeQsmClient()
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio.NetworkService, "status", return_value={"mode": "wifi"}),
            patch.object(audio, "_record"),
        ):
            asyncio.run(audio.audio_speak(SpeakRequest(text="指定离线。", mode="offline")))

        self.assertEqual(client.speak_calls[0][3], "offline")

    def test_qsm_client_sends_normalized_tts_mode(self) -> None:
        client = QsmClient(mode="real")
        with patch.object(client, "_qsm_action", return_value={"ok": True}) as action:
            client.audio_speak("测试", 280, 2.0, "INVALID")

        payload = action.call_args.args[1]
        self.assertEqual(payload["volume"], 255)
        self.assertEqual(payload["speed"], 1.8)
        self.assertEqual(payload["tts_mode"], "auto")


if __name__ == "__main__":
    unittest.main()
