from __future__ import annotations

import asyncio
import inspect
import json
import struct
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.local_asr_client import (  # noqa: E402
    LocalAsrClient,
    build_paraformer_payload,
    pcm16le_to_float32le,
    sherpa_transcript,
)
from app.services.qwen_realtime_tts import (  # noqa: E402
    QwenRealtimeTts,
    audio_delta,
    session_update_event,
)
from app.routers.audio import _open_qsm_mic_stream, _wait_for_cloud_asr_ready, audio_asr_realtime  # noqa: E402


class RealtimeAudioTest(unittest.TestCase):
    def test_pcm16_is_normalized_for_sherpa_websocket(self) -> None:
        source = struct.pack("<hhh", -32768, 0, 32767)

        converted = pcm16le_to_float32le(source)

        samples = struct.unpack("<fff", converted)
        self.assertAlmostEqual(samples[0], -1.0, places=5)
        self.assertAlmostEqual(samples[1], 0.0, places=5)
        self.assertAlmostEqual(samples[2], 32767 / 32768, places=5)

    def test_sherpa_result_keeps_partial_and_final_state(self) -> None:
        partial = sherpa_transcript(json.dumps({"text": "我有点头", "segment": 0, "final": False}))
        final = sherpa_transcript(json.dumps({"text": "我有点头晕", "segment": 0, "final": True}))
        paraformer = sherpa_transcript(json.dumps({"text": "我对青霉素和头孢过敏"}))

        self.assertEqual(partial, ("我有点头", False))
        self.assertEqual(final, ("我有点头晕", True))
        self.assertEqual(paraformer, ("我对青霉素和头孢过敏", True))
        self.assertIsNone(sherpa_transcript("Done!"))

    def test_paraformer_payload_contains_rate_length_and_float_pcm(self) -> None:
        source = struct.pack("<hhh", -32768, 0, 16384)

        payload = build_paraformer_payload(source, sample_rate=16000)

        rate, byte_count = struct.unpack("<II", payload[:8])
        samples = struct.unpack("<fff", payload[8:])
        self.assertEqual(rate, 16000)
        self.assertEqual(byte_count, 12)
        self.assertAlmostEqual(samples[0], -1.0, places=5)
        self.assertAlmostEqual(samples[1], 0.0, places=5)
        self.assertAlmostEqual(samples[2], 0.5, places=5)

    def test_qwen_session_accepts_an_explicit_voice_speed(self) -> None:
        event = session_update_event(speed=1.75)
        session = event["session"]

        self.assertEqual(event["type"], "session.update")
        self.assertEqual(session["mode"], "commit")
        self.assertEqual(session["response_format"], "pcm")
        self.assertEqual(session["sample_rate"], 24000)
        self.assertEqual(session["speech_rate"], 1.75)
        self.assertIn("语速", session["instructions"])

    def test_qwen_default_voice_uses_moderate_speed(self) -> None:
        session = session_update_event()["session"]

        self.assertEqual(session["speech_rate"], 1.32)
        self.assertNotIn("偏快", session["instructions"])

    def test_qwen_audio_delta_is_decoded_incrementally(self) -> None:
        event = {"type": "response.audio.delta", "delta": "AQIDBA=="}

        self.assertEqual(audio_delta(event), b"\x01\x02\x03\x04")
        self.assertEqual(audio_delta({"type": "response.done"}), b"")

    def test_qwen_tts_waits_for_unplayed_pcm_tail(self) -> None:
        audio_bytes = 24000 * 2 * 8

        self.assertEqual(QwenRealtimeTts.playback_drain_seconds(audio_bytes, 10.0, now=15.0), 3.45)
        self.assertEqual(QwenRealtimeTts.playback_drain_seconds(audio_bytes, 10.0, now=20.0), 0.35)
        self.assertEqual(QwenRealtimeTts.playback_drain_seconds(0, 10.0, now=10.0), 0.0)

    def test_qwen_tts_does_not_cut_a_long_unplayed_pcm_tail_at_eight_seconds(self) -> None:
        audio_bytes = 24000 * 2 * 30

        self.assertEqual(
            QwenRealtimeTts.playback_drain_seconds(audio_bytes, 10.0, now=15.0),
            25.45,
        )


class CloudAsrReadinessTest(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_asr_waits_for_manual_commit_instead_of_silence_vad(self) -> None:
        source = inspect.getsource(audio_asr_realtime)

        self.assertNotIn('"type": "server_vad"', source)
        self.assertIn('"type": "input_audio_buffer.commit"', source)

    async def test_qsm_microphone_stream_is_not_limited_to_45_seconds(self) -> None:
        source = inspect.getsource(_open_qsm_mic_stream)

        self.assertNotIn("duration=45", source)

    async def test_local_audio_collection_stops_without_waiting_for_stream_eof(self) -> None:
        microphone = asyncio.StreamReader()
        microphone.feed_data(struct.pack("<hhhh", -1000, 0, 1000, 2000))
        stopped = asyncio.Event()

        collect = asyncio.create_task(LocalAsrClient._collect_audio(microphone, stopped))
        await asyncio.sleep(0)
        stopped.set()

        pcm = await asyncio.wait_for(collect, timeout=0.5)
        self.assertEqual(pcm, struct.pack("<hhhh", -1000, 0, 1000, 2000))

    async def test_local_paraformer_uploads_one_complete_utterance(self) -> None:
        class Upstream:
            def __init__(self) -> None:
                self.sent: list[bytes | str] = []

            async def send(self, payload: bytes | str) -> None:
                self.sent.append(payload)

            async def recv(self) -> str:
                return json.dumps({"text": "我有点头晕"})

        microphone = asyncio.StreamReader()
        microphone.feed_data(struct.pack("<hhhh", -1000, 0, 1000, 2000))
        microphone.feed_eof()
        stopped = asyncio.Event()
        upstream = Upstream()

        results = [
            item
            async for item in LocalAsrClient().recognize_connected(upstream, microphone, stopped)
        ]

        binary = b"".join(item for item in upstream.sent if isinstance(item, bytes))
        self.assertEqual(struct.unpack("<II", binary[:8]), (16000, 16))
        self.assertEqual(results, [("我有点头晕", True)])
        self.assertTrue(upstream.sent)
        self.assertTrue(all(isinstance(item, bytes) for item in upstream.sent))

    async def test_recording_waits_for_session_updated(self) -> None:
        class Upstream:
            def __init__(self) -> None:
                self.events = iter(
                    [
                        json.dumps({"type": "session.created"}),
                        json.dumps({"type": "session.updated"}),
                    ]
                )
                self.read_count = 0

            async def recv(self) -> str:
                self.read_count += 1
                return next(self.events)

        upstream = Upstream()

        await _wait_for_cloud_asr_ready(upstream)

        self.assertEqual(upstream.read_count, 2)


if __name__ == "__main__":
    unittest.main()
