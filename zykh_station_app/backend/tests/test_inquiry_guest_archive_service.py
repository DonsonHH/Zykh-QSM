from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.repositories.inquiry_repository import InquiryRepository  # noqa: E402
from app.schemas.inquiry import InquirySessionResponse  # noqa: E402
from app.services.inquiry_guest_archive_service import InquiryGuestArchiveService  # noqa: E402


class CapturingCamera:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.capture_calls = 0

    def latest_frame(self, max_age_seconds: float):
        return self.source if self.capture_calls else None

    def capture(self):
        self.capture_calls += 1
        return {"ok": True, "error_message": None}


class InquiryGuestArchiveServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.root / "station.db"))
        self.db_patch.start()
        db.init_db()
        now = db.now_text()
        InquiryRepository().save_session(
            InquirySessionResponse(
                session_id="session-guest",
                user_name="访客",
                stage="symptoms",
                reply="",
                next_action="ask",
                title="访客问询",
                created_at=now,
                updated_at=now,
            )
        )
        self.source = self.root / "camera.jpg"
        self.source.write_bytes(b"\xff\xd8" + b"x" * 256 + b"\xff\xd9")

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_missing_cached_frame_triggers_a_real_capture_before_archiving(self) -> None:
        camera = CapturingCamera(self.source)
        service = InquiryGuestArchiveService(camera_service=camera)

        with patch(
            "app.services.inquiry_guest_archive_service.DispenseArchiveService._write_low_resolution",
            side_effect=lambda source, destination: shutil.copyfile(source, destination),
        ):
            result = service.capture_for_session("session-guest", "访客")

        self.assertTrue(result["ok"])
        self.assertEqual(camera.capture_calls, 1)
        self.assertTrue(Path(str(result["image_path"])).is_file())
        with db.connect() as conn:
            row = conn.execute(
                "SELECT status, guest_name FROM inquiry_guest_archives WHERE session_id=?",
                ("session-guest",),
            ).fetchone()
        self.assertEqual((row["status"], row["guest_name"]), ("captured", "访客"))


if __name__ == "__main__":
    unittest.main()
