from __future__ import annotations

from pydantic import BaseModel


class QsmStatus(BaseModel):
    ok: bool
    mode: str
    status_label: str
    vitals: dict[str, object]
    devices: dict[str, str]
    detail: str = ""
