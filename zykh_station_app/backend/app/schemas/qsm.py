from __future__ import annotations

from pydantic import BaseModel


class QsmStatus(BaseModel):
    ok: bool
    mode: str
    connected: bool
    base_url: str
    device_status: str
    vitals_status: str
    camera_status: str
    dispense_status: str
    error_message: str | None = None
    status_label: str
    vitals: dict[str, object]
    devices: dict[str, str]
    detail: str = ""
