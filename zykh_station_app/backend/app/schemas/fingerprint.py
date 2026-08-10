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
    total_matches: int = 0
    reserved_templates: int = 16
    error_message: str | None = None


class FingerprintActionResponse(BaseModel):
    ok: bool
    status: str
    user: ServiceUser | None = None
    template_id: int | None = None
    score: float | None = None
    match_count: int = 0
    last_seen_at: str | None = None
    job_id: str | None = None
    event: str | None = None
    message: str
    error_message: str | None = None
    verification_assertion_id: str = ""
