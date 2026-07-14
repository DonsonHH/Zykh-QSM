from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.qsm_client import QsmClient  # noqa: E402
from app.routers.qsm import qsm_vitals  # noqa: E402


QSM_RESPONSE = {
    "ok": True,
    "vitals": {
        "temperature": 36.4,
        "heart_rate": 74,
        "spo2": 98,
        "finger_detected": True,
        "quality": "stable",
        "source": "UART8-vitals-24B+GY-614",
    },
    "sensors": {
        "max30102": {
            "ok": True,
            "data": {
                "heart_rate_bpm": 74,
                "spo2_percent": 98,
                "microcirculation": 5,
                "systolic_pressure": 119,
                "diastolic_pressure": 78,
                "respiratory_rate": 16,
                "fatigue": 22,
                "rr_interval": 81,
                "hrv_sdnn": 43,
                "hrv_rmssd": 31,
                "body_temperature_c": 36.55,
                "ambient_temperature_c": 26.37,
                "reference_ready": True,
                "finger_detected": True,
                "quality": "stable",
                "sample_count": 4,
            },
        },
        "gy614": {"ok": True, "data": {"body_temp_c": 36.4}},
    },
}

QSM_PARTIAL_RESPONSE = {
    "ok": True,
    "vitals": {
        "temperature": 36.3,
        "heart_rate": 0,
        "spo2": 0,
        "finger_detected": False,
        "quality": "",
    },
    "sensors": {
        "max30102": {
            "ok": False,
            "error": "传感器读取失败",
            "detail": "No valid 24-byte frame received",
            "data": {
                "ok": False,
                "status": "unavailable",
                "source": "UART8-vitals-24B",
                "error": "No valid 24-byte frame received",
            },
        },
        "gy614": {"ok": True, "data": {"body_temp_c": 36.3}},
    },
}

QSM_FAILED_RESPONSE = {
    "ok": False,
    "vitals": {
        "temperature": 0,
        "heart_rate": 0,
        "spo2": 0,
        "finger_detected": False,
    },
    "sensors": {
        "max30102": {
            "ok": False,
            "error": "UART8 sensor unavailable",
            "data": {"ok": False, "source": "UART8-vitals-24B"},
        },
        "gy614": {"ok": False, "error": "GY614 unavailable"},
    },
}


class _QsmHandler(BaseHTTPRequestHandler):
    response_payload = QSM_RESPONSE

    def do_POST(self) -> None:  # noqa: N802
        body = json.dumps(self.response_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class QsmVitalsIntegrationTest(unittest.TestCase):
    def read_vitals(self, payload: dict[str, object]) -> dict[str, object]:
        handler = type("QsmHandler", (_QsmHandler,), {"response_payload": payload})
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = QsmClient(mode="real", base_url=f"http://127.0.0.1:{server.server_port}")
            return client.read_full_vitals()
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_full_vitals_preserve_integrated_uart_sensor_fields(self) -> None:
        result = self.read_vitals(QSM_RESPONSE)

        self.assertEqual(result["source"], "real")
        self.assertEqual(result["temperature_c"], 36.4)
        self.assertEqual(result["heart_rate"], 74)
        self.assertEqual(result["spo2"], 98)
        self.assertEqual(result["systolic_pressure"], 119)
        self.assertEqual(result["diastolic_pressure"], 78)
        self.assertEqual(result["respiratory_rate"], 16)
        self.assertEqual(result["hrv_sdnn"], 43)
        self.assertEqual(result["hrv_rmssd"], 31)
        self.assertEqual(result["microcirculation"], 5)
        self.assertEqual(result["sensor_body_temperature"], 36.55)
        self.assertEqual(result["ambient_temperature"], 26.37)
        self.assertTrue(result["reference_ready"])

    def test_temperature_remains_available_when_uart_sensor_fails(self) -> None:
        result = self.read_vitals(QSM_PARTIAL_RESPONSE)

        self.assertEqual(result["temperature_c"], 36.3)
        self.assertIsNone(result["heart_rate"])
        self.assertIsNone(result["spo2"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["quality"], "error")
        self.assertIn("No valid 24-byte frame received", result["error_message"])

    def test_top_level_failure_is_not_reported_as_real_measurement(self) -> None:
        result = self.read_vitals(QSM_FAILED_RESPONSE)

        self.assertEqual(result["source"], "unavailable")
        self.assertIsNone(result["temperature_c"])
        self.assertIsNone(result["heart_rate"])
        self.assertIsNone(result["spo2"])
        self.assertIn("UART8 sensor unavailable", result["error_message"])

    def test_public_endpoint_marks_unavailable_payload_as_failed(self) -> None:
        client = QsmClient(mode="real")
        client.read_full_vitals = lambda: {
            "temperature_c": None,
            "heart_rate": None,
            "spo2": None,
            "source": "unavailable",
            "error_message": "sensor timeout",
        }

        with (
            patch("app.routers.qsm.QsmClient", return_value=client),
            patch("app.routers.qsm.VitalsRepository.append"),
            patch("app.routers.qsm.DeviceActionRepository.append"),
        ):
            response = qsm_vitals(full=True)

        self.assertFalse(response.ok)
        self.assertEqual(response.status, "unavailable")
        self.assertIsNone(response.temperature)
        self.assertEqual(response.error_message, "sensor timeout")


if __name__ == "__main__":
    unittest.main()
