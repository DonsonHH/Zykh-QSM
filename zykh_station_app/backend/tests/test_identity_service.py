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
from app.services.identity_service import IdentityService  # noqa: E402


class FakeFaceClient:
    def __init__(self, identify_result: dict[str, object]) -> None:
        self.identify_result = identify_result
        self.enrolled_subjects: list[str] = []

    def identify(self, frames: int = 75) -> dict[str, object]:
        return self.identify_result

    def enroll(self, subject: str, samples: int = 18) -> dict[str, object]:
        self.enrolled_subjects.append(subject)
        return {"ok": True, "status": "enrolled", "subject": subject, "samples": samples}

    def status(self) -> dict[str, object]:
        return {"ok": True, "status": "available"}


class IdentityServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "identity.db"
        self.settings_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.settings_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_unknown_face_does_not_create_duplicate_profile(self) -> None:
        face = FakeFaceClient({"ok": True, "status": "unknown", "confidence": -1})
        result = IdentityService(face_client=face).resolve()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.user)
        self.assertEqual(face.enrolled_subjects, [])

    def test_matched_subject_returns_bound_service_user(self) -> None:
        face = FakeFaceClient({"ok": True, "status": "unknown", "confidence": -1})
        service = IdentityService(face_client=face)
        enrollment = service.enroll_user("zhangsan")
        self.assertTrue(enrollment.ok)

        matched_face = FakeFaceClient(
            {
                "ok": True,
                "status": "matched",
                "subject": "profile:zhangsan",
                "confidence": 0.82,
            }
        )
        result = IdentityService(face_client=matched_face).resolve()

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.user.id, "zhangsan")
        self.assertEqual(result.user.name, "张三")
        self.assertAlmostEqual(result.confidence, 0.82)

    def test_matched_unbound_subject_requires_admin_reenrollment(self) -> None:
        face = FakeFaceClient(
            {
                "ok": True,
                "status": "matched",
                "subject": "profile:removed-user",
                "confidence": 0.79,
            }
        )
        service = IdentityService(face_client=face)

        result = service.resolve()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "unbound")
        self.assertIsNone(result.user)
        self.assertEqual(result.subject, "profile:removed-user")
        self.assertEqual(face.enrolled_subjects, [])


if __name__ == "__main__":
    unittest.main()
