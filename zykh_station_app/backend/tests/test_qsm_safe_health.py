from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.services.qsm_client import QsmClient  # noqa: E402


class QsmSafeHealthTest(unittest.TestCase):
    def test_simulated_network_mode_checks_gateway_without_requesting_network_status(self) -> None:
        client = QsmClient(mode="real", base_url="http://qsm.invalid")

        with (
            patch(
                "app.services.qsm_client.settings",
                replace(settings, network_demo_simulate=True),
            ),
            patch.object(
                client,
                "_request_json",
                return_value=({"ok": True, "offline_available": True}, None),
            ) as request,
        ):
            status = client.get_qsm_status()

        self.assertTrue(status.connected)
        self.assertEqual(status.vitals_status, "unavailable")
        self.assertEqual(status.camera_status, "reserved")
        request.assert_called_once_with("/api/audio/status", timeout=settings.qsm_timeout_seconds)

    def test_physical_network_mode_keeps_full_gateway_status_available(self) -> None:
        client = QsmClient(mode="real", base_url="http://qsm.invalid")

        with (
            patch(
                "app.services.qsm_client.settings",
                replace(settings, network_demo_simulate=False),
            ),
            patch.object(
                client,
                "_request_json",
                return_value=({"ok": True}, None),
            ) as request,
        ):
            status = client.get_qsm_status()

        self.assertTrue(status.connected)
        request.assert_called_once_with("/api/status", timeout=settings.qsm_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
