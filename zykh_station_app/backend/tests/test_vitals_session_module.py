from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.modules.vitals_session import VitalsSessionModule  # noqa: E402
from app.repositories.sync_repository import SyncRepository  # noqa: E402
from app.repositories.vitals_repository import VitalsRecord, VitalsRepository  # noqa: E402
from app.services.cloud_sync_service import CloudSyncWorker  # noqa: E402


class InMemoryVitalsGateway:
    def __init__(self, status_payload: dict[str, object]) -> None:
        self.status_payload = status_payload
        self.prepare_count = 0
        self.replace_active_requested: bool | None = None
        self.cancelled_session_id = ""

    def prepare_vitals(self) -> dict[str, object]:
        self.prepare_count += 1
        return {"ok": True, "status": "prepared"}

    def start_vitals_session(self, *, replace_active: bool = True) -> dict[str, object]:
        self.replace_active_requested = replace_active
        return {
            "ok": True,
            "session_id": "module-session",
            "status": "starting",
            "hardware_started": True,
        }

    def get_vitals_session(self, session_id: str) -> dict[str, object]:
        return {**self.status_payload, "session_id": session_id}

    def cancel_vitals_session(self, session_id: str) -> dict[str, object]:
        self.cancelled_session_id = session_id
        return {
            "ok": True,
            "session_id": session_id,
            "status": "cancelled",
            "hardware_started": False,
        }


class VitalsSessionModuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "vitals-module.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_complete_real_measurement_is_persisted_once_through_module_interface(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "complete",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": 72,
                "spo2": 98,
                "temperature_source": "gy614_sensor",
                "heart_rate_source": "uart8_sensor",
                "spo2_source": "uart8_sensor",
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-05T15:00:00+08:00",
            }
        )
        module = VitalsSessionModule(gateway=gateway)

        first = module.get("module-session")
        second = module.get("module-session")

        self.assertEqual(first.status, "complete")
        self.assertEqual(second.session_id, "module-session")
        self.assertEqual(VitalsRepository().count(), 1)
        self.assertEqual(SyncRepository().get_status().pending_count, 1)

    def test_demo_fallback_is_returned_but_never_persisted_through_module_interface(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
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
                "measured_at": "2026-08-05T15:05:00+08:00",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-demo")

        self.assertEqual(response.status, "complete")
        self.assertEqual(response.spo2_source, "demo_fallback")
        self.assertEqual(VitalsRepository().count(), 0)
        self.assertEqual(SyncRepository().get_status().pending_count, 0)

    def test_failed_measurement_keeps_current_values_separate_from_history(self) -> None:
        VitalsRepository().append(
            VitalsRecord(
                id="previous-complete",
                temperature=36.4,
                heart_rate=75,
                spo2=98,
                status="available",
                source="UART-vitals",
                measured_at="2026-08-05T14:00:00+08:00",
            )
        )
        gateway = InMemoryVitalsGateway(
            {
                "ok": False,
                "mode": "real",
                "status": "failed",
                "hardware_started": True,
                "temperature": 36.6,
                "heart_rate": None,
                "spo2": None,
                "temperature_source": "gy614_sensor",
                "failure_reason": "no_finger",
                "error_message": "手指信号未稳定。",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-history")

        self.assertEqual(response.status, "failed")
        self.assertEqual(response.temperature, 36.6)
        self.assertIsNone(response.heart_rate)
        self.assertIsNone(response.spo2)
        self.assertTrue(response.historical_fallback)
        self.assertEqual(response.historical_temperature, 36.4)
        self.assertEqual(response.historical_heart_rate, 75)
        self.assertEqual(response.historical_spo2, 98)
        self.assertEqual(VitalsRepository().count(), 1)
        snapshot = CloudSyncWorker._build_snapshot()["vitals"]
        self.assertEqual([item["id"] for item in snapshot], ["previous-complete"])
        self.assertFalse(any(key.startswith("historical_") for key in snapshot[0]))

    def test_lifecycle_interface_preserves_session_identity_and_replace_choice(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "starting",
                "hardware_started": True,
            }
        )
        module = VitalsSessionModule(gateway=gateway)

        prepared = module.prepare()
        started = module.start(replace_active=False)
        cancelled = module.cancel(started.session_id)

        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(gateway.prepare_count, 1)
        self.assertFalse(gateway.replace_active_requested)
        self.assertEqual(started.session_id, "module-session")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(gateway.cancelled_session_id, "module-session")

    def test_gateway_diagnostics_and_provenance_cross_the_module_interface(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
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
                "source": "UART8-vitals-24B+GY-614",
                "measured_at": "2026-08-05T15:10:00+08:00",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-diagnostics")

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

    def test_replaced_session_keeps_its_lifecycle_reason(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": True,
                "mode": "real",
                "status": "cancelled",
                "hardware_started": False,
                "communication_status": "receiving_protocol_frames",
                "cancel_reason": "replaced",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-replaced")

        self.assertEqual(response.status, "cancelled")
        self.assertEqual(response.cancel_reason, "replaced")
        self.assertIsNone(response.failure_reason)

    def test_failed_measurement_without_history_stays_failed_without_reference(self) -> None:
        gateway = InMemoryVitalsGateway(
            {
                "ok": False,
                "mode": "real",
                "status": "failed",
                "hardware_started": True,
                "temperature": 36.5,
                "heart_rate": None,
                "spo2": None,
                "failure_reason": "no_finger",
            }
        )

        response = VitalsSessionModule(gateway=gateway).get("module-no-history")

        self.assertEqual(response.status, "failed")
        self.assertFalse(response.historical_fallback)


if __name__ == "__main__":
    unittest.main()
