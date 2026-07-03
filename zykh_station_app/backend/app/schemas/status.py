from __future__ import annotations

from pydantic import BaseModel


class StatusChip(BaseModel):
    id: str
    label: str
    value: str
    tone: str = "soft"


class ApiStatus(BaseModel):
    ok: bool = True
    network_mode: str
    ai_mode: str
    device_status: str
    sync_status: str
    qsm_mode: str
    qsm_connected: bool
    qsm_error_message: str | None = None
    dry_run: bool
    chips: list[StatusChip]
