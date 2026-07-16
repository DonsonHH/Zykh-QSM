from __future__ import annotations

from fastapi import APIRouter, Query

from ..schemas.identity import FaceEnrollmentResponse, IdentityResponse, IdentityStatusResponse
from ..services.identity_service import IdentityService


router = APIRouter(prefix="/api/identity", tags=["identity"])


@router.get("/status", response_model=IdentityStatusResponse)
def identity_status() -> IdentityStatusResponse:
    return IdentityService().status()


@router.post("/resolve", response_model=IdentityResponse)
def resolve_identity() -> IdentityResponse:
    return IdentityService().resolve()


@router.post("/verify-dispense", response_model=IdentityResponse)
def verify_dispense_identity(samples: int = Query(default=18, ge=10, le=30)) -> IdentityResponse:
    return IdentityService().verify_for_dispense(samples=samples)


@router.post("/enroll/{user_id}", response_model=FaceEnrollmentResponse)
def enroll_identity(user_id: str, samples: int = Query(default=18, ge=10, le=30)) -> FaceEnrollmentResponse:
    return IdentityService().enroll_user(user_id, samples=samples)
