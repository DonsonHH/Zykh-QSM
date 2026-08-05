from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.repositories.sync_repository import SyncRepository  # noqa: E402
from app.repositories.vitals_repository import VitalsRecord, VitalsRepository  # noqa: E402
from app.routers.vitals import get_vitals_session  # noqa: E402
from app.services.cloud_sync_service import CloudSyncWorker  # noqa: E402
from app.services.qsm_client import QsmClient  # noqa: E402


class _SessionHandler(BaseHTTPRequestHandler):
    cancelled = False
    start_payload = None
    start_response_payload = None
    status_payload = None
    drop_start_requests = 0
    drop_cancel_requests = 0
    drop_status_requests = 0
    status_delay_seconds = 0.0

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/vitals/session/start":
            if type(self).drop_start_requests > 0:
                type(self).drop_start_requests -= 1
                self.close_connection = True
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            type(self).start_payload = json.loads(self.rfile.read(content_length) or b"{}")
            self._json(
                type(self).start_response_payload
                or {
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
            if type(self).drop_cancel_requests > 0:
                type(self).drop_cancel_requests -= 1
                self.close_connection = True
                return
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
            if type(self).drop_status_requests > 0:
                type(self).drop_status_requests -= 1
                self.close_connection = True
                return
            if type(self).status_delay_seconds > 0:
                delay = type(self).status_delay_seconds
                type(self).status_delay_seconds = 0.0
                time.sleep(delay)
            self._json(
                type(self).status_payload
                or {
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
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


class VitalsSessionClientTest(unittest.TestCase):
    def setUp(self) -> None:
        handler = type(
            "SessionHandler",
            (_SessionHandler,),
            {
                "cancelled": False,
                "start_payload": None,
                "start_response_payload": None,
                "status_payload": None,
                "drop_start_requests": 0,
                "drop_cancel_requests": 0,
                "drop_status_requests": 0,
                "status_delay_seconds": 0.0,
            },
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

    def test_start_transport_failure_exposes_machine_readable_diagnostics(self) -> None:
        self.handler.drop_start_requests = 1

        result = self.client.start_vitals_session()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["communication_status"], "gateway_unreachable")
        self.assertEqual(result["failure_reason"], "transport_error")

    def test_start_rejection_preserves_gateway_failure_diagnostics(self) -> None:
        self.handler.start_response_payload = {
            "ok": False,
            "session_id": "session-rejected",
            "status": "failed",
            "hardware_started": False,
            "communication_status": "gateway_available",
            "failure_reason": "hardware_start_timeout",
            "error_message": "hardware did not acknowledge start",
        }

        result = self.client.start_vitals_session()

        self.assertFalse(result["ok"])
        self.assertEqual(result["session_id"], "session-rejected")
        self.assertEqual(result["communication_status"], "gateway_available")
        self.assertEqual(result["failure_reason"], "hardware_start_timeout")

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

    def test_status_uses_demo_spo2_only_when_other_core_readings_are_real(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "elapsed_seconds": 18.0,
            "heart_rate": 76,
            "spo2": None,
            "temperature": 36.4,
            "finger_detected": True,
            "heart_rate_frame_count": 3,
            "spo2_frame_count": 0,
            "source": "UART8-vitals-24B+GY-614",
            "error_message": "血氧仍未稳定。",
        }
        with patch(
            "app.services.qsm_client.settings",
            SimpleNamespace(
                qsm_vitals_session_status_path="/api/vitals/session/status",
                vitals_demo_spo2_fallback=True,
            ),
        ):
            result = self.client.get_vitals_session("session-123")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "complete")
        self.assertGreaterEqual(result["spo2"], 95)
        self.assertLessEqual(result["spo2"], 99)
        self.assertTrue(result["spo2_demo_fallback"])
        self.assertEqual(result["temperature_source"], "gy614_sensor")
        self.assertEqual(result["heart_rate_source"], "uart8_sensor")
        self.assertEqual(result["spo2_source"], "demo_fallback")

    def test_cancel_calls_board_session_gateway(self) -> None:
        result = self.client.cancel_vitals_session("session-123")

        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(self.handler.cancelled)

    def test_cancel_transport_failure_exposes_machine_readable_diagnostics(self) -> None:
        self.handler.drop_cancel_requests = 1

        result = self.client.cancel_vitals_session("session-123")

        self.assertFalse(result["ok"])
        self.assertEqual(result["session_id"], "session-123")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["communication_status"], "gateway_unreachable")
        self.assertEqual(result["failure_reason"], "transport_error")

    def test_transient_status_disconnect_is_classified_without_losing_next_result(self) -> None:
        self.handler.drop_status_requests = 1

        interrupted = self.client.get_vitals_session("session-123")
        recovered = self.client.get_vitals_session("session-123")

        self.assertFalse(interrupted["ok"])
        self.assertEqual(interrupted["status"], "failed")
        self.assertEqual(interrupted["communication_status"], "gateway_unreachable")
        self.assertEqual(interrupted["failure_reason"], "transport_error")
        self.assertIn("暂不可用", interrupted["error_message"])
        self.assertEqual(recovered["status"], "complete")
        self.assertEqual(recovered["heart_rate"], 74)
        self.assertFalse(
            self.handler.cancelled,
            "a transient status disconnect must not cancel the board session",
        )

    def test_status_timeout_is_classified_and_keeps_session_identity(self) -> None:
        self.handler.status_delay_seconds = 3.2

        result = self.client.get_vitals_session("session-123")

        self.assertFalse(result["ok"])
        self.assertEqual(result["session_id"], "session-123")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["communication_status"], "gateway_unreachable")
        self.assertEqual(result["failure_reason"], "transport_error")
        self.assertIn("超时", result["error_message"])

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

    def test_demo_spo2_session_is_not_persisted_or_marked_for_sync(self) -> None:
        payload = {
            "ok": True,
            "mode": "real",
            "session_id": "session-demo-spo2",
            "status": "complete",
            "hardware_started": True,
            "temperature": 36.6,
            "heart_rate": 72,
            "spo2": 97,
            "temperature_source": "gy614_sensor",
            "heart_rate_source": "uart8_sensor",
            "spo2_source": "demo_fallback",
            "spo2_demo_fallback": True,
            "source": "UART8-vitals-24B+GY-614",
            "measured_at": "2026-08-05T00:12:00+08:00",
        }

        with patch("app.routers.vitals.QsmClient") as client_class:
            client_class.return_value.get_vitals_session.return_value = payload
            response = get_vitals_session("session-demo-spo2")

        self.assertEqual(response.status, "complete")
        self.assertEqual(response.spo2_source, "demo_fallback")
        self.assertTrue(response.spo2_demo_fallback)
        self.assertEqual(VitalsRepository().count(), 0)
        sync_status = SyncRepository().get_status()
        self.assertEqual(sync_status.pending_count, 0)

    def test_session_response_preserves_gateway_diagnostics_and_provenance(self) -> None:
        payload = {
            "ok": True,
            "mode": "real",
            "session_id": "session-diagnostics",
            "status": "complete",
            "hardware_started": True,
            "temperature": 36.6,
            "heart_rate": 72,
            "spo2": 98,
            "temperature_source": "gy614_sensor",
            "heart_rate_source": "uart8_sensor",
            "spo2_source": "uart8_sensor",
            "stable_core": True,
            "communication_status": "receiving_protocol_frames",
            "valid_frame_count": 8,
            "contact_frame_count": 6,
            "heart_rate_frame_count": 5,
            "spo2_frame_count": 4,
            "first_heart_rate_frame": 3,
            "first_spo2_frame": 5,
            "spo2_stabilization_extended": True,
            "prewarmed": True,
            "prewarm_age": 2.4,
            "minimum_measurement_seconds": 5.6,
            "failure_reason": None,
            "source": "UART8-vitals-24B+GY-614",
            "measured_at": "2026-08-04T21:00:00+08:00",
        }

        with patch("app.routers.vitals.QsmClient") as client_class:
            client_class.return_value.get_vitals_session.return_value = payload
            response = get_vitals_session("session-diagnostics")

        self.assertTrue(response.stable_core)
        self.assertEqual(response.communication_status, "receiving_protocol_frames")
        self.assertEqual(response.valid_frame_count, 8)
        self.assertEqual(response.contact_frame_count, 6)
        self.assertEqual(response.heart_rate_frame_count, 5)
        self.assertEqual(response.spo2_frame_count, 4)
        self.assertEqual(response.first_heart_rate_frame, 3)
        self.assertEqual(response.first_spo2_frame, 5)
        self.assertTrue(response.spo2_stabilization_extended)
        self.assertTrue(response.prewarmed)
        self.assertEqual(response.prewarm_age, 2.4)
        self.assertEqual(response.minimum_measurement_seconds, 5.6)
        self.assertEqual(response.temperature_source, "gy614_sensor")
        self.assertEqual(response.heart_rate_source, "uart8_sensor")
        self.assertEqual(response.spo2_source, "uart8_sensor")
        self.assertIsNone(response.failure_reason)

    def test_replaced_session_preserves_cancel_reason(self) -> None:
        payload = {
            "ok": True,
            "mode": "real",
            "session_id": "session-replaced",
            "status": "cancelled",
            "hardware_started": False,
            "communication_status": "receiving_protocol_frames",
            "cancel_reason": "replaced",
            "updated_at": "2026-08-04T21:00:00+08:00",
        }

        with patch("app.routers.vitals.QsmClient") as client_class:
            client_class.return_value.get_vitals_session.return_value = payload
            response = get_vitals_session("session-replaced")

        self.assertEqual(response.status, "cancelled")
        self.assertEqual(response.cancel_reason, "replaced")

    def test_unstable_finger_signal_attaches_history_without_completing_session(self) -> None:
        VitalsRepository().append(
            VitalsRecord(
                id="previous-complete",
                temperature=36.4,
                heart_rate=75,
                spo2=98,
                status="available",
                source="UART-vitals",
                measured_at="2026-07-20T10:20:00+08:00",
            )
        )
        payload = {
            "ok": False,
            "mode": "real",
            "session_id": "session-unstable-finger",
            "status": "failed",
            "hardware_started": True,
            "temperature": 36.6,
            "heart_rate": None,
            "spo2": None,
            "temperature_source": "gy614_sensor",
            "source": "UART-vitals",
            "error_message": "手指信号未稳定。",
        }

        with patch("app.routers.vitals.QsmClient") as client_class:
            client_class.return_value.get_vitals_session.return_value = payload
            response = get_vitals_session("session-unstable-finger")

        self.assertFalse(response.ok)
        self.assertEqual(response.status, "failed")
        self.assertEqual(response.temperature, 36.6)
        self.assertIsNone(response.heart_rate)
        self.assertIsNone(response.spo2)
        self.assertEqual(response.temperature_source, "gy614_sensor")
        self.assertIsNone(response.heart_rate_source)
        self.assertIsNone(response.spo2_source)
        self.assertTrue(response.historical_fallback)
        self.assertEqual(response.historical_temperature, 36.4)
        self.assertEqual(response.historical_heart_rate, 75)
        self.assertEqual(response.historical_spo2, 98)
        self.assertEqual(response.historical_source, "UART-vitals")
        self.assertEqual(response.historical_measured_at, "2026-07-20T10:20:00+08:00")
        self.assertEqual(response.error_message, "手指信号未稳定。")
        self.assertEqual(VitalsRepository().count(), 1)
        self.assertEqual(SyncRepository().get_status().pending_count, 0)
        snapshot_vitals = CloudSyncWorker._build_snapshot()["vitals"]
        self.assertEqual([item["id"] for item in snapshot_vitals], ["previous-complete"])
        self.assertFalse(
            any(key.startswith("historical_") for item in snapshot_vitals for key in item),
            "historical reference fields must not become a cloud vitals snapshot",
        )

    def test_unstable_finger_signal_stays_failed_without_history(self) -> None:
        payload = {
            "ok": False,
            "mode": "real",
            "session_id": "session-no-history",
            "status": "failed",
            "hardware_started": True,
            "temperature": 36.5,
            "heart_rate": None,
            "spo2": None,
            "error_message": "手指信号未稳定。",
        }

        with patch("app.routers.vitals.QsmClient") as client_class:
            client_class.return_value.get_vitals_session.return_value = payload
            response = get_vitals_session("session-no-history")

        self.assertFalse(response.ok)
        self.assertEqual(response.status, "failed")
        self.assertFalse(response.historical_fallback)


if __name__ == "__main__":
    unittest.main()
