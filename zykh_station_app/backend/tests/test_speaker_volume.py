from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.speaker_volume import (  # noqa: E402
    canonicalize_speaker_gain,
    speaker_gain_to_percent,
    speaker_percent_to_gain,
)


class SpeakerVolumeTest(unittest.TestCase):
    def test_calibrated_key_points(self) -> None:
        expected = {0: 0, 1: 128, 10: 136, 25: 151, 50: 180, 75: 214, 85: 230, 90: 238, 100: 255}
        self.assertEqual({percent: speaker_percent_to_gain(percent) for percent in expected}, expected)
        self.assertEqual(speaker_gain_to_percent(230), 85)

    def test_entire_visible_scale_is_monotonic_and_round_trips(self) -> None:
        gains = [speaker_percent_to_gain(percent) for percent in range(101)]
        self.assertEqual(gains, sorted(gains))
        self.assertGreaterEqual(len(set(gains[1:])), 98)
        for percent, gain in enumerate(gains):
            self.assertLessEqual(abs(speaker_gain_to_percent(gain) - percent), 1)

    def test_legacy_inaudible_values_preserve_their_old_slider_intent(self) -> None:
        self.assertEqual(canonicalize_speaker_gain(1), 146)
        self.assertEqual(canonicalize_speaker_gain(8), 180)
        self.assertEqual(canonicalize_speaker_gain(45), 214)
        self.assertEqual(canonicalize_speaker_gain(127), 238)
        self.assertEqual(canonicalize_speaker_gain(128), 128)
        self.assertEqual(canonicalize_speaker_gain(230), 230)


if __name__ == "__main__":
    unittest.main()
