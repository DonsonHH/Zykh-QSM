from __future__ import annotations

import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from uuid import uuid4

from .. import db
from .dispense_archive_service import DispenseArchiveService
from .qsm_camera_service import QsmCameraService


class InquiryGuestArchiveService:
    def __init__(self, camera_service: QsmCameraService | None = None) -> None:
        self.camera_service = camera_service or QsmCameraService()

    @property
    def archive_dir(self) -> Path:
        return Path(db.settings.db_path).parent / "inquiry_guest_archives"

    def schedule_capture(self, session_id: str, guest_name: str) -> None:
        worker = threading.Thread(
            target=self._capture_safely,
            args=(session_id, guest_name),
            name=f"inquiry-guest-archive-{session_id[-6:]}",
            daemon=True,
        )
        worker.start()

    def _capture_safely(self, session_id: str, guest_name: str) -> None:
        try:
            self.capture_for_session(session_id, guest_name)
        except (OSError, sqlite3.Error):
            return

    def capture_for_session(self, session_id: str, guest_name: str) -> dict[str, object]:
        archive_id = f"inquiry-guest-{uuid4().hex[:12]}"
        source = self.camera_service.latest_frame(max_age_seconds=45)
        capture_error = ""
        if source is None or not source.is_file():
            captured = self.camera_service.capture()
            capture_error = str(captured.get("error_message") or "")
            if captured.get("ok"):
                source = self.camera_service.latest_frame(max_age_seconds=10)
        if source is None or not source.is_file():
            return self._save(
                archive_id,
                session_id,
                guest_name,
                status="unavailable",
                image_path="",
                error_message=capture_error or "访客问询开始时未取得可用摄像头画面。",
            )

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        destination = self.archive_dir / f"{session_id}.jpg"
        error_message = ""
        try:
            DispenseArchiveService._write_low_resolution(source, destination)
        except (OSError, subprocess.SubprocessError) as exc:
            try:
                shutil.copyfile(source, destination)
                error_message = f"低分辨率转换未完成，已保存原始画面：{exc}"
            except OSError as copy_error:
                return self._save(
                    archive_id,
                    session_id,
                    guest_name,
                    status="unavailable",
                    image_path="",
                    error_message=f"访客问询照片保存失败：{copy_error}",
                )
        return self._save(
            archive_id,
            session_id,
            guest_name,
            status="captured",
            image_path=str(destination),
            error_message=error_message,
        )

    @staticmethod
    def _save(
        archive_id: str,
        session_id: str,
        guest_name: str,
        *,
        status: str,
        image_path: str,
        error_message: str,
    ) -> dict[str, object]:
        db.init_db()
        captured_at = db.now_text()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO inquiry_guest_archives(
                  id, session_id, guest_name, captured_at, image_path, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  guest_name=excluded.guest_name,
                  captured_at=excluded.captured_at,
                  image_path=excluded.image_path,
                  status=excluded.status,
                  error_message=excluded.error_message
                """,
                (archive_id, session_id, guest_name, captured_at, image_path, status, error_message),
            )
        return {
            "ok": status == "captured",
            "id": archive_id,
            "status": status,
            "image_path": image_path,
            "error_message": error_message,
        }
