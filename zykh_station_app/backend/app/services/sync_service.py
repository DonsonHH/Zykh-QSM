from __future__ import annotations

from ..db import now_text
from ..repositories.sync_repository import SyncRepository
from ..config import settings
from ..schemas.sync import SyncMockResponse, SyncStatus
from .cloud_sync_service import CloudSyncError, cloud_sync_worker


class SyncService:
    def __init__(self, repository: SyncRepository | None = None) -> None:
        self.repository = repository or SyncRepository()

    def get_status(self) -> SyncStatus:
        return cloud_sync_worker.runtime_status(self.repository.get_status())

    def mock_sync(self) -> SyncMockResponse:
        if settings.cloud_sync_enabled and settings.cloud_sync_endpoint.strip():
            try:
                synced_count, message = cloud_sync_worker.run_once()
            except CloudSyncError as exc:
                detail = str(exc)
                if "本地模式" in detail:
                    return SyncMockResponse(
                        synced_count=0,
                        message=detail,
                        status=self.get_status(),
                    )
                return SyncMockResponse(
                    synced_count=0,
                    message=f"云端暂不可用，本地数据将继续排队：{detail}",
                    status=self.get_status(),
                )
            return SyncMockResponse(synced_count=synced_count, message=message, status=self.get_status())

        current = self.repository.get_status()
        if not settings.sync_endpoint:
            status = SyncStatus(
                sync_status="已同步",
                pending_count=0,
                last_sync_at=now_text(),
                network_mode=current.network_mode or "家庭网络",
            )
            self.repository.save_status(status)
            return SyncMockResponse(
                synced_count=0,
                message="当前记录已在本地保存。",
                status=status,
            )
        return SyncMockResponse(
            synced_count=0,
            message="旧同步端点已停用，请配置 CLOUD_SYNC_ENDPOINT。",
            status=current,
        )
