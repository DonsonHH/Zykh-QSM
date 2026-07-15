from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.local_asr_client import (  # noqa: E402
    pcm16le_to_float32le,
    sherpa_transcript,
)
from app.services.qwen_realtime_tts import (  # noqa: E402
    audio_delta,
    session_update_event,
)


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

        self.assertEqual(partial, ("我有点头", False))
        self.assertEqual(final, ("我有点头晕", True))
        self.assertIsNone(sherpa_transcript("Done!"))

    def test_qwen_session_uses_fast_realtime_voice(self) -> None:
        event = session_update_event(speed=1.75)
        session = event["session"]

        self.assertEqual(event["type"], "session.update")
        self.assertEqual(session["mode"], "commit")
        self.assertEqual(session["response_format"], "pcm")
        self.assertEqual(session["sample_rate"], 24000)
        self.assertEqual(session["speech_rate"], 1.75)
        self.assertIn("语速", session["instructions"])

    def test_qwen_audio_delta_is_decoded_incrementally(self) -> None:
        event = {"type": "response.audio.delta", "delta": "AQIDBA=="}

        self.assertEqual(audio_delta(event), b"\x01\x02\x03\x04")
        self.assertEqual(audio_delta({"type": "response.done"}), b"")


if __name__ == "__main__":
    unittest.main()
