from __future__ import annotations

from .. import db
from ..schemas.sync import SyncStatus


DEFAULT_SYNC_STATUS = SyncStatus(
    sync_status="已同步",
    pending_count=0,
    last_sync_at="刚刚",
    network_mode="家庭网络",
)


class SyncRepository:
    def get_status(self) -> SyncStatus:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT sync_status, pending_count, last_sync_at, network_mode FROM sync_state WHERE id=1"
            ).fetchone()
        if not row:
            return DEFAULT_SYNC_STATUS
        status = SyncStatus(**dict(row))
        if status.pending_count == 0 and status.sync_status in {"未配置", "待同步"}:
            return SyncStatus(
                sync_status="已同步",
                pending_count=0,
                last_sync_at=status.last_sync_at if status.last_sync_at and status.last_sync_at != "未同步" else "刚刚",
                network_mode=status.network_mode or "家庭网络",
            )
        return status

    def save_status(self, status: SyncStatus) -> SyncStatus:
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state(id, sync_status, pending_count, last_sync_at, network_mode)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  sync_status=excluded.sync_status,
                  pending_count=excluded.pending_count,
                  last_sync_at=excluded.last_sync_at,
                  network_mode=excluded.network_mode
                """,
                (status.sync_status, status.pending_count, status.last_sync_at, status.network_mode),
            )
        return status
