from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.repositories.sync_repository import SyncRepository  # noqa: E402
from app.repositories.vitals_repository import VitalsRepository  # noqa: E402
from app.routers.vitals import get_vitals_session  # noqa: E402
from app.services.qsm_client import QsmClient  # noqa: E402


class _SessionHandler(BaseHTTPRequestHandler):
    cancelled = False
    start_payload = None

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/vitals/session/start":
            content_length = int(self.headers.get("Content-Length", "0"))
            type(self).start_payload = json.loads(self.rfile.read(content_length) or b"{}")
            self._json(
                {
                    "ok": True,
                    "session_id": "session-123",
                    "status": "starting",
                    "hardware_started": True,
                    "started_at": "2026-07-18T09:00:00+0800",
                    "updated_at": "2026-07-18T09:00:00+0800",
                }
            )
            return
        if self.path.startswith("/api/vitals/session/cancel"):
            type(self).cancelled = True
            self._json(
                {
                    "ok": True,
                    "session_id": "session-123",
                    "status": "cancelled",
                    "hardware_started": True,
                }
            )
            return
        self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/vitals/session/status"):
            self._json(
                {
                    "ok": True,
                    "session_id": "session-123",
                    "status": "complete",
                    "hardware_started": True,
                    "elapsed_seconds": 5.2,
                    "heart_rate": 74,
                    "spo2": 98,
                    "temperature": 36.5,
                    "systolic_pressure": 119,
                    "hrv_sdnn": 42,
                    "body_temperature": 35.9,
                    "ambient_temperature": 24.8,
                    "reference_ready": True,
                    "finger_detected": True,
                    "quality": "good",
                    "message": "Integrated UART vitals measurement received",
                    "sample_count": 4,
                    "source": "UART8-vitals-24B+GY-614",
                    "measured_at": "2026-07-18T09:00:05+0800",
                }
            )
            return
        self.send_error(404)

    def _json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class VitalsSessionClientTest(unittest.TestCase):
    def setUp(self) -> None:
        handler = type(
            "SessionHandler",
            (_SessionHandler,),
            {"cancelled": False, "start_payload": None},
        )
        self.handler = handler
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = QsmClient(
            mode="real",
            vitals_base_url=f"http://127.0.0.1:{self.server.server_port}",
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def test_start_requires_hardware_acknowledgement(self) -> None:
        result = self.client.start_vitals_session()

        self.assertTrue(result["ok"])
        self.assertTrue(result["hardware_started"])
        self.assertEqual(result["status"], "starting")
        self.assertEqual(result["session_id"], "session-123")
        self.assertEqual(self.handler.start_payload, {"replace_active": True})

    def test_status_preserves_core_and_optional_metrics(self) -> None:
        result = self.client.get_vitals_session("session-123")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["heart_rate"], 74)
        self.assertEqual(result["spo2"], 98)
        self.assertEqual(result["temperature"], 36.5)
        self.assertEqual(result["systolic_pressure"], 119)
        self.assertEqual(result["hrv_sdnn"], 42)
        self.assertEqual(result["body_temperature"], 35.9)
        self.assertEqual(result["ambient_temperature"], 24.8)
        self.assertTrue(result["reference_ready"])
        self.assertEqual(result["quality"], "good")

    def test_cancel_calls_board_session_gateway(self) -> None:
        result = self.client.cancel_vitals_session("session-123")

        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(self.handler.cancelled)

    def test_mock_session_is_complete_with_three_core_values(self) -> None:
        started = QsmClient(mode="mock").start_vitals_session()
        result = QsmClient(mode="mock").get_vitals_session(str(started["session_id"]))

        self.assertTrue(started["hardware_started"])
        self.assertEqual(result["status"], "complete")
        self.assertGreater(result["heart_rate"], 0)
        self.assertGreater(result["spo2"], 0)
        self.assertGreater(result["temperature"], 0)


class VitalsSessionPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "vitals-session.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_completed_session_is_persisted_once_for_cloud_sync(self) -> None:
        payload = {
            "ok": True,
            "mode": "real",
            "session_id": "session-cloud-123",
            "status": "complete",
            "hardware_started": True,
            "temperature": 36.6,
            "heart_rate": 72,
            "spo2": 98,
            "quality": "good",
            "source": "UART-vitals",
            "measured_at": "2026-07-20T14:30:00+08:00",
        }
        with patch("app.routers.vitals.QsmClient") as client_class:
            client_class.return_value.get_vitals_session.return_value = payload
            get_vitals_session("session-cloud-123")
            get_vitals_session("session-cloud-123")

        latest = VitalsRepository().latest()
        self.assertEqual(VitalsRepository().count(), 1)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, "vitals-session-session-cloud-123")
        self.assertEqual(latest.heart_rate, 72)
        self.assertEqual(latest.spo2, 98)
        self.assertEqual(latest.temperature, 36.6)
        sync_status = SyncRepository().get_status()
        self.assertEqual(sync_status.sync_status, "待同步")
        self.assertEqual(sync_status.pending_count, 1)


if __name__ == "__main__":
    unittest.main()
