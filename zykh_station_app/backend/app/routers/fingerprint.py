from __future__ import annotations

from fastapi import APIRouter, Query

from ..schemas.fingerprint import FingerprintActionResponse, FingerprintStatusResponse
from ..services.fingerprint_service import FingerprintService


router = APIRouter(prefix="/api/fingerprint", tags=["fingerprint"])


@router.get("/status", response_model=FingerprintStatusResponse)
def fingerprint_status() -> FingerprintStatusResponse:
    return FingerprintService().status()


@router.post("/identify", response_model=FingerprintActionResponse)
def identify_fingerprint(timeout: int = Query(default=45, ge=5, le=60)) -> FingerprintActionResponse:
    return FingerprintService().identify(timeout=timeout)


@router.post("/enroll/{user_id}", response_model=FingerprintActionResponse)
def enroll_fingerprint(user_id: str, timeout: int = Query(default=45, ge=10, le=60)) -> FingerprintActionResponse:
    return FingerprintService().enroll_user(user_id, timeout=timeout)


@router.delete("/{user_id}", response_model=FingerprintActionResponse)
def delete_fingerprint(user_id: str) -> FingerprintActionResponse:
    return FingerprintService().delete_user(user_id)
