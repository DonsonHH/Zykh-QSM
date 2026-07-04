from __future__ import annotations

from pydantic import BaseModel

from .. import db


class DeviceActionRecord(BaseModel):
    id: str
    created_at: str
    type: str
    title: str
    description: str
    target_user: str = "家庭药柜"
    status: str = "已记录"
    sync_status: str = "待同步"


class DeviceActionRepository:
    def list_records(self) -> list[DeviceActionRecord]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, type, title, description, target_user, status, sync_status
                FROM device_action_records
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [DeviceActionRecord(**dict(row)) for row in rows]

    def append(self, record: DeviceActionRecord) -> DeviceActionRecord:
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO device_action_records(
                  id, created_at, type, title, description, target_user, status, sync_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.created_at,
                    record.type,
                    record.title,
                    record.description,
                    record.target_user,
                    record.status,
                    record.sync_status,
                ),
            )
        return record
