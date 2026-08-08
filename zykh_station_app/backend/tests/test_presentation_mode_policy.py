from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.presentation_mode import PresentationModePolicy  # noqa: E402


class PresentationModePolicyTest(unittest.TestCase):
    def test_online_mode_uses_cloud_services_and_realtime_sync(self) -> None:
        route = PresentationModePolicy.resolve("sim")

        self.assertEqual(route.display_mode, "online")
        self.assertEqual(route.ai_mode, "cloud")
        self.assertEqual(route.tts_mode, "cloud")
        self.assertTrue(route.realtime_sync_enabled)

    def test_offline_demo_mode_keeps_cloud_ai_but_uses_qsm_voice(self) -> None:
        route = PresentationModePolicy.resolve("local")

        self.assertEqual(route.display_mode, "local")
        self.assertEqual(route.ai_mode, "cloud")
        self.assertEqual(route.tts_mode, "offline")
        self.assertFalse(route.realtime_sync_enabled)

    def test_legacy_offline_value_maps_to_the_same_demo_route(self) -> None:
        self.assertEqual(
            PresentationModePolicy.resolve("offline"),
            PresentationModePolicy.resolve("local"),
        )


if __name__ == "__main__":
    unittest.main()
