from __future__ import annotations

from pydantic import BaseModel


class SyncStatus(BaseModel):
    sync_status: str
    pending_count: int
    last_sync_at: str
    network_mode: str


class SyncMockResponse(BaseModel):
    ok: bool = True
    synced_count: int
    message: str
    status: SyncStatus
