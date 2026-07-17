from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from .. import db
from ..schemas.dispense import DispenseRecord
from .qsm_camera_service import QsmCameraService


class DispenseArchiveService:
    def __init__(self, camera_service: QsmCameraService | None = None) -> None:
        self.camera_service = camera_service or QsmCameraService()

    @property
    def archive_dir(self) -> Path:
        return Path(db.settings.db_path).parent / "identity_archives"

    def capture_for_record(self, record: DispenseRecord) -> dict[str, object]:
        archive_id = f"identity-{uuid4().hex[:12]}"
        source = self.camera_service.latest_frame(max_age_seconds=45)
        if source is None or not source.is_file():
            return self._save_metadata(
                archive_id,
                record,
                status="unavailable",
                image_path="",
                error_message="识别预览未留下可用画面。",
            )

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        destination = self.archive_dir / f"{record.id}.jpg"
        error_message = ""
        try:
            self._write_low_resolution(source, destination)
        except (OSError, subprocess.SubprocessError) as exc:
            try:
                shutil.copyfile(source, destination)
                error_message = f"低分辨率转换未完成，已保存原始预览帧：{exc}"
            except OSError as copy_error:
                return self._save_metadata(
                    archive_id,
                    record,
                    status="unavailable",
                    image_path="",
                    error_message=f"取药照片保存失败：{copy_error}",
                )

        result = self._save_metadata(
            archive_id,
            record,
            status="captured",
            image_path=str(destination),
            error_message=error_message,
        )
        self._prune(120)
        return result

    def list_recent(self, limit: int = 8) -> list[dict[str, object]]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, dispense_record_id, target_user_name, medicine_name,
                       captured_at, image_path, status, error_message
                FROM dispense_identity_archives
                ORDER BY captured_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 20)),),
            ).fetchall()
        items: list[dict[str, object]] = []
        for row in rows:
            path = Path(str(row["image_path"] or ""))
            thumbnail = ""
            try:
                if path.is_file() and path.stat().st_size <= 1_500_000:
                    thumbnail = "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
            except OSError:
                thumbnail = ""
            items.append(
                {
                    "id": str(row["id"]),
                    "dispense_record_id": str(row["dispense_record_id"]),
                    "target_user_name": str(row["target_user_name"]),
                    "medicine_name": str(row["medicine_name"]),
                    "captured_at": str(row["captured_at"]),
                    "status": str(row["status"]),
                    "thumbnail_data_url": thumbnail,
                    "error_message": str(row["error_message"] or ""),
                }
            )
        return items

    @staticmethod
    def _write_low_resolution(source: Path, destination: Path) -> None:
        temporary = destination.with_name(f".{destination.stem}.tmp.jpg")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            "scale=480:320:force_original_aspect_ratio=decrease",
            "-q:v",
            "7",
            str(temporary),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size < 100:
            temporary.unlink(missing_ok=True)
            raise subprocess.SubprocessError((result.stderr or "ffmpeg 未生成有效图片").strip())
        temporary.replace(destination)

    @staticmethod
    def _save_metadata(
        archive_id: str,
        record: DispenseRecord,
        *,
        status: str,
        image_path: str,
        error_message: str,
    ) -> dict[str, object]:
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO dispense_identity_archives(
                  id, dispense_record_id, target_user_name, medicine_name,
                  captured_at, image_path, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dispense_record_id) DO UPDATE SET
                  target_user_name=excluded.target_user_name,
                  medicine_name=excluded.medicine_name,
                  captured_at=excluded.captured_at,
                  image_path=excluded.image_path,
                  status=excluded.status,
                  error_message=excluded.error_message
                """,
                (
                    archive_id,
                    record.id,
                    record.target_user_name,
                    record.medicine_name,
                    record.created_at,
                    image_path,
                    status,
                    error_message,
                ),
            )
        return {
            "ok": status == "captured",
            "id": archive_id,
            "status": status,
            "image_path": image_path,
            "error_message": error_message,
        }

    def _prune(self, keep: int) -> None:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, image_path
                FROM dispense_identity_archives
                ORDER BY captured_at DESC, id DESC
                LIMIT -1 OFFSET ?
                """,
                (max(1, keep),),
            ).fetchall()
            for row in rows:
                path = Path(str(row["image_path"] or ""))
                try:
                    if path.is_file() and path.parent == self.archive_dir:
                        path.unlink()
                except OSError:
                    pass
                conn.execute("DELETE FROM dispense_identity_archives WHERE id=?", (row["id"],))
