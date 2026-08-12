from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

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
            "temperature_source": "gy614_sensor",
            "finger_detected": True,
            "heart_rate_frame_count": 3,
            "heart_rate_source": "uart8_sensor",
            "spo2_frame_count": 0,
            "failure_reason": "spo2_not_stable",
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
        self.assertEqual(result["quality"], "demo_fallback")
        self.assertEqual(result["completion_reason"], "spo2_not_stable")

    def test_status_accepts_latest_sensor_values_when_core_signal_is_not_stable(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "heart_rate": 78,
            "spo2": 96,
            "temperature": 36.5,
            "temperature_source": "gy614_sensor",
            "heart_rate_source": "uart8_sensor",
            "spo2_source": "uart8_sensor",
            "stable_core": False,
            "failure_reason": "core_not_stable",
            "source": "UART8-vitals-24B+GY-614",
            "error_message": "心率和血氧读数已出现，但信号不连续。",
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
        self.assertEqual(result["heart_rate"], 78)
        self.assertEqual(result["spo2"], 96)
        self.assertEqual(result["temperature"], 36.5)
        self.assertEqual(result["heart_rate_source"], "uart8_sensor")
        self.assertEqual(result["spo2_source"], "uart8_sensor")
        self.assertEqual(result["quality"], "approximate")
        self.assertEqual(result["completion_reason"], "core_not_stable")
        self.assertIsNone(result["failure_reason"])

    def test_status_fills_missing_heart_rate_and_spo2_with_classified_values(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "elapsed_seconds": 18.0,
            "heart_rate": None,
            "spo2": None,
            "temperature": 36.4,
            "temperature_source": "gy614_sensor",
            "finger_detected": False,
            "failure_reason": "no_finger",
            "source": "UART8-vitals-24B+GY-614",
            "error_message": "未获得心率和血氧。",
        }
        with patch(
            "app.services.qsm_client.settings",
            SimpleNamespace(
                qsm_vitals_session_status_path="/api/vitals/session/status",
                vitals_demo_spo2_fallback=True,
            ),
        ):
            result = self.client.get_vitals_session("session-123")
            repeated = self.client.get_vitals_session("session-123")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "complete")
        self.assertGreaterEqual(result["heart_rate"], 70)
        self.assertLessEqual(result["heart_rate"], 100)
        self.assertGreaterEqual(result["spo2"], 95)
        self.assertLessEqual(result["spo2"], 99)
        self.assertEqual(repeated["heart_rate"], result["heart_rate"])
        self.assertEqual(repeated["spo2"], result["spo2"])
        self.assertEqual(result["heart_rate_source"], "demo_fallback")
        self.assertEqual(result["spo2_source"], "demo_fallback")
        self.assertTrue(result["spo2_demo_fallback"])
        self.assertIsNone(result["failure_reason"])
        self.assertEqual(result["demo_fallback_reason"], "no_finger")
        self.assertEqual(result["completion_reason"], "no_finger")
        self.assertEqual(result["quality"], "demo_fallback")

    def test_status_does_not_mask_no_protocol_frames_with_demo_values(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "heart_rate": None,
            "spo2": None,
            "temperature": 36.4,
            "temperature_source": "gy614_sensor",
            "failure_reason": "no_protocol_frames",
        }
        with patch(
            "app.services.qsm_client.settings",
            SimpleNamespace(
                qsm_vitals_session_status_path="/api/vitals/session/status",
                vitals_demo_spo2_fallback=True,
            ),
        ):
            result = self.client.get_vitals_session("session-123")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "no_protocol_frames")
        self.assertIsNone(result["heart_rate"])
        self.assertIsNone(result["spo2"])

    def test_status_preserves_real_spo2_when_only_heart_rate_needs_demo_fallback(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "heart_rate": None,
            "spo2": 98,
            "temperature": 36.5,
            "temperature_source": "gy614_sensor",
            "spo2_source": "uart8_sensor",
            "failure_reason": "heart_rate_not_stable",
            "source": "UART8-vitals-24B+GY-614",
        }
        with patch(
            "app.services.qsm_client.settings",
            SimpleNamespace(
                qsm_vitals_session_status_path="/api/vitals/session/status",
                vitals_demo_spo2_fallback=True,
            ),
        ):
            result = self.client.get_vitals_session("session-123")

        self.assertGreaterEqual(result["heart_rate"], 70)
        self.assertLessEqual(result["heart_rate"], 100)
        self.assertEqual(result["heart_rate_source"], "demo_fallback")
        self.assertEqual(result["spo2"], 98)
        self.assertEqual(result["spo2_source"], "uart8_sensor")
        self.assertFalse(result.get("spo2_demo_fallback", False))

    def test_status_does_not_mask_transport_error_with_demo_values(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "heart_rate": None,
            "spo2": None,
            "temperature": 36.5,
            "failure_reason": "transport_error",
            "communication_status": "gateway_unreachable",
        }
        with patch(
            "app.services.qsm_client.settings",
            SimpleNamespace(
                qsm_vitals_session_status_path="/api/vitals/session/status",
                vitals_demo_spo2_fallback=True,
            ),
        ):
            result = self.client.get_vitals_session("session-123")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "transport_error")
        self.assertIsNone(result["heart_rate"])
        self.assertIsNone(result["spo2"])

    def test_status_requires_verified_real_temperature_provenance_for_demo_fallback(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "heart_rate": None,
            "spo2": None,
            "temperature": 36.5,
            "temperature_source": "",
            "failure_reason": "core_not_stable",
        }
        with patch(
            "app.services.qsm_client.settings",
            SimpleNamespace(
                qsm_vitals_session_status_path="/api/vitals/session/status",
                vitals_demo_spo2_fallback=True,
            ),
        ):
            result = self.client.get_vitals_session("session-123")

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["heart_rate"])
        self.assertIsNone(result["spo2"])

    def test_status_requires_forehead_temperature_for_demo_fallback(self) -> None:
        self.handler.status_payload = {
            "ok": False,
            "session_id": "session-123",
            "status": "failed",
            "hardware_started": True,
            "heart_rate": None,
            "spo2": None,
            "temperature": 35.9,
            "temperature_source": "uart8_fingertip_reference",
            "failure_reason": "core_not_stable",
        }
        with patch(
            "app.services.qsm_client.settings",
            SimpleNamespace(
                qsm_vitals_session_status_path="/api/vitals/session/status",
                vitals_demo_spo2_fallback=True,
            ),
        ):
            result = self.client.get_vitals_session("session-123")

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["heart_rate"])
        self.assertIsNone(result["spo2"])

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


if __name__ == "__main__":
    unittest.main()
