from __future__ import annotations

from pydantic import BaseModel

from .records import ServiceUser


class FingerprintStatusResponse(BaseModel):
    ok: bool
    status: str
    device: str | None = None
    count: int = 0
    capacity: int = 300
    bound_users: int = 0
    reserved_templates: int = 16
    error_message: str | None = None


class FingerprintActionResponse(BaseModel):
    ok: bool
    status: str
    user: ServiceUser | None = None
    template_id: int | None = None
    score: float | None = None
    message: str
    error_message: str | None = None
