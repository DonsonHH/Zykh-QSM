from __future__ import annotations

from pydantic import BaseModel

from .records import ServiceUser


class IdentityResponse(BaseModel):
    ok: bool
    status: str
    user: ServiceUser | None = None
    subject: str | None = None
    confidence: float | None = None
    match_count: int = 0
    last_seen_at: str | None = None
    message: str
    error_message: str | None = None
    new_guest: bool = False


class FaceEnrollmentResponse(IdentityResponse):
    samples: int | None = None


class IdentityStatusResponse(BaseModel):
    ok: bool
    status: str
    camera_available: bool = False
    runtime_available: bool = False
    enrolled_samples: int = 0
    bound_users: int = 0
    error_message: str | None = None
