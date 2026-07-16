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
from app.services.fingerprint_service import FingerprintService  # noqa: E402


class FakeFingerprintClient:
    def __init__(self) -> None:
        self.match_id = 16
        self.deleted: list[int] = []
        self.enrolled: list[int] = []
        self.progress_event = "place_finger_first"
        self.power_actions: list[str] = []

    def status(self) -> dict[str, object]:
        return {"ok": True, "status": "available", "count": 1, "capacity": 300}

    def identify(self, timeout: int = 45) -> dict[str, object]:
        return {"ok": True, "matched": True, "id": self.match_id, "score": 126}

    def enroll(self, template_id: int, timeout: int = 45) -> dict[str, object]:
        self.enrolled.append(template_id)
        return {"ok": True, "status": "enrolled", "event": "enrolled", "id": template_id}

    def start_enrollment(self, template_id: int, timeout: int = 60) -> dict[str, object]:
        self.enrolled.append(template_id)
        return {"ok": True, "status": "running", "event": "place_finger_first", "job_id": "job-1", "id": template_id}

    def enrollment_progress(self, job_id: str) -> dict[str, object]:
        if self.progress_event == "enrolled":
            return {"ok": True, "status": "enrolled", "event": "enrolled", "job_id": job_id, "id": 16}
        return {"ok": True, "status": "running", "event": self.progress_event, "job_id": job_id, "id": 16}

    def delete(self, template_id: int) -> dict[str, object]:
        self.deleted.append(template_id)
        return {"ok": True, "status": "deleted", "id": template_id}

    def standby(self) -> dict[str, object]:
        self.power_actions.append("standby")
        return {"ok": True, "status": "complete"}

    def wake(self) -> dict[str, object]:
        self.power_actions.append("wake")
        return {"ok": True, "status": "complete"}


class TimeoutFingerprintClient(FakeFingerprintClient):
    def identify(self, timeout: int = 45) -> dict[str, object]:
        return {"ok": False, "status": "error", "error_message": "finger_wait_timeout"}


class FingerprintServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fingerprint.db"
        self.settings_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.settings_patch.start()
        db.init_db()
        self.client = FakeFingerprintClient()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_unbound_board_template_does_not_resolve_user(self) -> None:
        result = FingerprintService(client=self.client).identify()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "unbound")
        self.assertEqual(result.template_id, 16)
        self.assertIsNone(result.user)

    def test_enrolled_template_resolves_service_user(self) -> None:
        service = FingerprintService(client=self.client)
        enrollment = service.enroll_user("zhangsan")
        identified = service.identify()

        self.assertTrue(enrollment.ok)
        self.assertEqual(enrollment.template_id, 16)
        self.assertEqual(self.client.enrolled, [16])
        self.assertTrue(identified.ok)
        self.assertEqual(identified.user.id, "zhangsan")
        self.assertEqual(identified.score, 126)
        self.assertEqual(identified.match_count, 1)
        self.assertIsNotNone(identified.last_seen_at)

        identified_again = service.identify()
        status = service.status()

        self.assertEqual(identified_again.match_count, 2)
        self.assertEqual(status.total_matches, 2)

    def test_driver_timeout_is_translated_for_terminal_user(self) -> None:
        result = FingerprintService(client=TimeoutFingerprintClient()).identify(timeout=5)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "timeout")
        self.assertNotIn("finger_wait_timeout", result.message)
        self.assertIn("未检测到手指", result.message)

    def test_async_enrollment_exposes_removal_step_then_binds_on_completion(self) -> None:
        service = FingerprintService(client=self.client)
        started = service.start_enrollment("zhangsan")

        self.assertTrue(started.ok)
        self.assertEqual(started.status, "running")
        self.assertEqual(started.job_id, "job-1")
        self.client.progress_event = "remove_finger"
        removal = service.enrollment_progress("zhangsan", "job-1")
        self.assertEqual(removal.event, "remove_finger")
        self.assertIn("完全移开", removal.message)

        self.client.progress_event = "enrolled"
        completed = service.enrollment_progress("zhangsan", "job-1")
        identified = service.identify()

        self.assertTrue(completed.ok)
        self.assertEqual(completed.status, "enrolled")
        self.assertTrue(identified.ok)
        self.assertEqual(identified.user.id, "zhangsan")
        self.assertEqual(self.client.deleted, [])

    def test_removal_timeout_has_actionable_message(self) -> None:
        response = FingerprintService._failure(
            {"ok": False, "status": "error", "error_message": "finger_removal_timeout"},
            "fallback",
        )

        self.assertFalse(response.ok)
        self.assertNotIn("finger_removal_timeout", response.message)
        self.assertIn("完全抬起", response.message)

    def test_fingerprint_light_can_enter_standby_and_wake(self) -> None:
        service = FingerprintService(client=self.client)

        standby = service.standby()
        wake = service.wake()

        self.assertTrue(standby.ok)
        self.assertEqual(standby.status, "standby")
        self.assertTrue(wake.ok)
        self.assertEqual(self.client.power_actions, ["standby", "wake"])


if __name__ == "__main__":
    unittest.main()
