from __future__ import annotations

import sys
import asyncio
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.routers import audio  # noqa: E402
from app.routers.audio import BeepRequest, SpeakRequest  # noqa: E402
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
    def test_local_display_mode_forces_qsm_offline_tts(self) -> None:
        client = FakeQsmClient()
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio.db, "get_setting", return_value="local"),
            patch.object(audio, "_record"),
        ):
            result = asyncio.run(audio.audio_speak(SpeakRequest(text="请安全用药。", volume=230, speed=1.2)))

        self.assertEqual(client.speak_calls, [("请安全用药。", 230, 1.2, "offline")])
        self.assertEqual(result["engine"], "offline-sherpa-onnx")
        self.assertTrue(result["offline"])

    def test_online_network_uses_auto_mode(self) -> None:
        client = FakeQsmClient()
        realtime = FakeRealtimeTts(client)
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch("app.services.speech_service.QwenRealtimeTts", return_value=realtime),
            patch.object(audio, "_read_api_key", return_value="private"),
            patch.object(audio.db, "get_setting", return_value="sim"),
            patch.object(audio, "_record"),
        ):
            result = asyncio.run(audio.audio_speak(SpeakRequest(text="联网播报。", volume=230)))

        self.assertEqual(client.speak_calls, [])
        self.assertEqual(realtime.calls[0][0], "联网播报。")
        self.assertEqual(result["engine"], "qwen-realtime-pcm")
        self.assertEqual(result["first_audio_ms"], 320)

    def test_local_display_mode_cannot_be_overridden_with_cloud_mode(self) -> None:
        client = FakeQsmClient()
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio.db, "get_setting", return_value="local"),
            patch.object(audio, "_record"),
        ):
            asyncio.run(audio.audio_speak(SpeakRequest(text="指定云端。", volume=230, mode="cloud")))

        self.assertEqual(client.speak_calls, [("指定云端。", 230, None, "offline")])

    def test_online_mode_cannot_be_overridden_with_offline_mode(self) -> None:
        client = FakeQsmClient()
        realtime = FakeRealtimeTts(client)
        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch("app.services.speech_service.QwenRealtimeTts", return_value=realtime),
            patch.object(audio, "_read_api_key", return_value="private"),
            patch.object(audio.db, "get_setting", return_value="sim"),
            patch.object(audio, "_record"),
        ):
            asyncio.run(audio.audio_speak(SpeakRequest(text="指定离线。", volume=230, mode="offline")))

        self.assertEqual(realtime.calls[0][0], "指定离线。")
        self.assertEqual(client.speak_calls, [])

    def test_asr_mode_is_not_changed_by_display_preference(self) -> None:
        with patch.object(audio.db, "get_setting", return_value="local") as get_setting:
            self.assertEqual(audio._asr_mode_for_network(), "cloud")

        get_setting.assert_not_called()

    def test_asr_mode_uses_cloud_for_connected_preference(self) -> None:
        with patch.object(audio.db, "get_setting", return_value="sim"):
            self.assertEqual(audio._asr_mode_for_network(), "cloud")

    def test_qsm_client_sends_normalized_tts_mode(self) -> None:
        client = QsmClient(mode="real")
        with patch.object(client, "_qsm_action", return_value={"ok": True}) as action:
            client.audio_speak("测试", 280, 2.0, "INVALID")

        payload = action.call_args.args[1]
        self.assertEqual(payload["volume"], 255)
        self.assertEqual(payload["speed"], 1.45)
        self.assertEqual(payload["tts_mode"], "auto")

    def test_zero_volume_beep_never_reaches_board_gateway(self) -> None:
        client = QsmClient(mode="real")
        with patch.object(client, "_qsm_action") as action:
            result = client.audio_beep(0)

        self.assertTrue(result["ok"])
        self.assertTrue(result["muted"])
        action.assert_not_called()

    def test_zero_volume_beep_route_does_not_create_qsm_client(self) -> None:
        with (
            patch.object(audio, "QsmClient") as client,
            patch.object(audio, "_record"),
        ):
            result = audio.audio_beep(BeepRequest(volume=0))

        self.assertTrue(result["muted"])
        client.assert_not_called()

    def test_stream_stop_cancels_an_active_tts_request(self) -> None:
        client = FakeQsmClient()

        class BlockingRealtimeTts:
            def __init__(self, _client) -> None:
                pass

            async def speak(self, *_args, **_kwargs):
                await asyncio.Event().wait()

        async def scenario() -> tuple[dict[str, object], dict[str, object]]:
            task = asyncio.create_task(audio.audio_speak(SpeakRequest(text="正在播报", volume=230)))
            await asyncio.sleep(0)
            stopped = await audio.audio_stream_stop()
            return await task, stopped

        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch("app.services.speech_service.QwenRealtimeTts", BlockingRealtimeTts),
            patch.object(audio, "_read_api_key", return_value="private"),
            patch.object(audio.db, "get_setting", return_value="sim"),
            patch.object(audio, "_record"),
        ):
            speak_result, stopped = asyncio.run(scenario())

        self.assertTrue(speak_result["cancelled"])
        self.assertTrue(stopped["ok"])
        self.assertEqual(stopped["cancelled_tts"], 1)
        self.assertEqual(client.stop_calls, 1)

    def test_stream_stop_waits_for_cancelled_offline_tts_before_final_stop(self) -> None:
        class BlockingOfflineQsmClient(FakeQsmClient):
            def __init__(self) -> None:
                super().__init__()
                self.started = threading.Event()
                self.release = threading.Event()
                self.events: list[str] = []

            def audio_speak(self, text, volume=None, speed=None, tts_mode="auto"):
                self.events.append(f"speak:start:{text}")
                self.started.set()
                if not self.release.wait(timeout=2):
                    raise TimeoutError("test did not release the stale offline speech")
                self.events.append(f"speak:finish:{text}")
                return super().audio_speak(text, volume, speed, tts_mode)

            def audio_stream_stop(self):
                self.events.append("stop")
                return super().audio_stream_stop()

        client = BlockingOfflineQsmClient()

        async def scenario():
            speak_task = asyncio.create_task(
                audio.audio_speak(SpeakRequest(text="一号柜指示灯已亮", volume=230))
            )
            started = await asyncio.to_thread(client.started.wait, 1)
            self.assertTrue(started, "offline QSM speech never entered the blocking call")
            stop_task = asyncio.create_task(audio.audio_stream_stop())
            await asyncio.sleep(0.05)
            stop_returned_before_stale_speech = stop_task.done()
            client.release.set()
            speak_result, stopped = await asyncio.gather(speak_task, stop_task)
            next_result = await audio.audio_speak(
                SpeakRequest(text="二号柜取药确认", volume=230)
            )
            return stop_returned_before_stale_speech, speak_result, stopped, next_result

        with (
            patch.object(audio, "QsmClient", return_value=client),
            patch.object(audio.db, "get_setting", return_value="local"),
            patch.object(audio, "_record"),
        ):
            returned_early, speak_result, stopped, next_result = asyncio.run(scenario())

        self.assertEqual(
            client.events,
            [
                "speak:start:一号柜指示灯已亮",
                "speak:finish:一号柜指示灯已亮",
                "stop",
                "speak:start:二号柜取药确认",
                "speak:finish:二号柜取药确认",
            ],
        )
        self.assertFalse(
            returned_early,
            "stop returned while the cancelled offline worker could still replay stale speech",
        )
        self.assertTrue(speak_result["cancelled"])
        self.assertTrue(stopped["ok"])
        self.assertEqual(stopped["cancelled_tts"], 1)
        self.assertTrue(next_result["ok"])


if __name__ == "__main__":
    unittest.main()
