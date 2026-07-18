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
        self.stop_calls = 0

    def audio_stream_stop(self) -> dict[str, object]:
        self.stop_calls += 1
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
            patch.object(audio.db, "get_setting", return_value="local"),
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
            patch.object(audio.db, "get_setting", return_value="sim"),
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
            patch.object(audio.db, "get_setting", return_value="local"),
            patch.object(audio, "_record"),
        ):
            asyncio.run(audio.audio_speak(SpeakRequest(text="指定云端。", mode="cloud")))

        self.assertEqual(client.speak_calls[0][3], "offline")

    def test_online_request_can_explicitly_select_offline_mode(self) -> None:
        client = FakeQsmClient()
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio.db, "get_setting", return_value="sim"),
            patch.object(audio, "_record"),
        ):
            asyncio.run(audio.audio_speak(SpeakRequest(text="指定离线。", mode="offline")))

        self.assertEqual(client.speak_calls[0][3], "offline")

    def test_asr_mode_uses_fast_persisted_preference(self) -> None:
        with patch.object(audio.db, "get_setting", return_value="local") as get_setting:
            self.assertEqual(audio._asr_mode_for_network(), "local")

        get_setting.assert_called_once_with("network_mode", audio.settings.network_preferred_mode)

    def test_asr_mode_uses_cloud_for_connected_preference(self) -> None:
        with patch.object(audio.db, "get_setting", return_value="sim"):
            self.assertEqual(audio._asr_mode_for_network(), "cloud")

    def test_qsm_client_sends_normalized_tts_mode(self) -> None:
        client = QsmClient(mode="real")
        with patch.object(client, "_qsm_action", return_value={"ok": True}) as action:
            client.audio_speak("测试", 280, 2.0, "INVALID")

        payload = action.call_args.args[1]
        self.assertEqual(payload["volume"], 255)
        self.assertEqual(payload["speed"], 1.8)
        self.assertEqual(payload["tts_mode"], "auto")

    def test_stream_stop_cancels_an_active_tts_request(self) -> None:
        client = FakeQsmClient()

        class BlockingRealtimeTts:
            def __init__(self, _client) -> None:
                pass

            async def speak(self, *_args, **_kwargs):
                await asyncio.Event().wait()

        async def scenario() -> tuple[dict[str, object], dict[str, object]]:
            task = asyncio.create_task(audio.audio_speak(SpeakRequest(text="正在播报")))
            await asyncio.sleep(0)
            stopped = await audio.audio_stream_stop()
            return await task, stopped

        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio, "QwenRealtimeTts", BlockingRealtimeTts),
            patch.object(audio, "_read_api_key", return_value="private"),
            patch.object(audio.db, "get_setting", return_value="sim"),
            patch.object(audio, "_record"),
        ):
            speak_result, stopped = asyncio.run(scenario())

        self.assertTrue(speak_result["cancelled"])
        self.assertTrue(stopped["ok"])
        self.assertEqual(stopped["cancelled_tts"], 1)
        self.assertEqual(client.stop_calls, 1)


if __name__ == "__main__":
    unittest.main()
