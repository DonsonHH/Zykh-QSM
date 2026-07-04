from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..db import now_text
from ..repositories.sync_repository import SyncRepository
from ..config import settings
from ..schemas.sync import SyncMockResponse, SyncStatus


class SyncService:
    def __init__(self, repository: SyncRepository | None = None) -> None:
        self.repository = repository or SyncRepository()

    def get_status(self) -> SyncStatus:
        return self.repository.get_status()

    def mock_sync(self) -> SyncMockResponse:
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
        payload = {
            "pending_count": current.pending_count,
            "generated_at": now_text(),
            "source": "zykh_station_app",
        }
        request = Request(
            settings.sync_endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        error_message = "同步端点未返回成功状态。"
        try:
            with urlopen(request, timeout=10) as response:
                ok = 200 <= response.status < 300
        except HTTPError as exc:
            ok = False
            error_message = f"同步端点 HTTP {exc.code}"
        except (URLError, TimeoutError, OSError) as exc:
            ok = False
            error_message = f"同步端点暂不可用：{exc}"

        if not ok:
            status = SyncStatus(
                sync_status="待同步",
                pending_count=current.pending_count,
                last_sync_at=current.last_sync_at,
                network_mode=current.network_mode,
            )
            self.repository.save_status(status)
            return SyncMockResponse(
                synced_count=0,
                message=error_message,
                status=status,
            )

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
            message="同步端点已确认，本地待同步记录已更新。",
            status=status,
        )
