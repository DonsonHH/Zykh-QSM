from __future__ import annotations

from pydantic import BaseModel


class SyncStatus(BaseModel):
    sync_status: str
    pending_count: int
    last_sync_at: str
    network_mode: str
    connected: bool = False
    device_id: str = ""
    last_error: str = ""
    last_command_at: str = ""
    interval_seconds: float = 0


class SyncMockResponse(BaseModel):
    ok: bool = True
    synced_count: int
    message: str
    status: SyncStatus
