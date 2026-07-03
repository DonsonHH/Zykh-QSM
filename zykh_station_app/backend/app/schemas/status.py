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
    dry_run: bool
    chips: list[StatusChip]
