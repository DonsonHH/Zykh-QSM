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
from app.schemas.dispense import DispenseRecord  # noqa: E402
from app.services.dispense_archive_service import DispenseArchiveService  # noqa: E402


class CameraWithFrame:
    def __init__(self, frame_path: Path) -> None:
        self.frame_path = frame_path

    def latest_frame(self, max_age_seconds: int = 45) -> Path:
        return self.frame_path


class DispenseArchiveServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "station.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        self.frame_path = self.root / "preview.jpg"
        self.frame_path.write_bytes(b"\xff\xd8" + b"preview-frame" * 20 + b"\xff\xd9")

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_capture_persists_small_preview_and_admin_thumbnail(self) -> None:
        service = DispenseArchiveService(camera_service=CameraWithFrame(self.frame_path))
        record = DispenseRecord(
            id="dispense-guest-1",
            medicine_id="slot-08-huoxiang-zhengqi",
            medicine_name="藿香正气丸",
            slot="slot-08",
            hardware_slot=8,
            quantity=1,
            unit="盒",
            reason="访客取药",
            dry_run=False,
            message="柜门已打开",
            qsm_ok=True,
            target_user_name="游客（未识别人脸）",
            target_user_type="guest",
            verification_method="face_guest_confirmed",
            created_at="2026-07-17 12:00:00",
        )

        with patch.object(
            DispenseArchiveService,
            "_write_low_resolution",
            side_effect=lambda source, destination: shutil.copyfile(source, destination),
        ):
            result = service.capture_for_record(record)

        self.assertTrue(result["ok"])
        saved_path = Path(str(result["image_path"]))
        self.assertTrue(saved_path.is_file())
        self.assertEqual(saved_path.parent, self.root / "identity_archives")

        items = service.list_recent()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_user_name"], "游客（未识别人脸）")
        self.assertEqual(items[0]["medicine_name"], "藿香正气丸")
        self.assertTrue(str(items[0]["thumbnail_data_url"]).startswith("data:image/jpeg;base64,"))


if __name__ == "__main__":
    unittest.main()
