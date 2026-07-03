from __future__ import annotations

from ..db import now_text
from ..repositories.sync_repository import SyncRepository
from ..schemas.sync import SyncMockResponse, SyncStatus


class SyncService:
    def __init__(self, repository: SyncRepository | None = None) -> None:
        self.repository = repository or SyncRepository()

    def get_status(self) -> SyncStatus:
        return self.repository.get_status()

    def mock_sync(self) -> SyncMockResponse:
        current = self.repository.get_status()
        synced_count = current.pending_count
        status = SyncStatus(
            sync_status="已同步",
            pending_count=0,
            last_sync_at=now_text(),
            network_mode=current.network_mode,
        )
        self.repository.save_status(status)
        return SyncMockResponse(
            synced_count=synced_count,
            message="模拟同步完成，本阶段仅更新本地同步状态。",
            status=status,
        )
