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


@router.post("/standby", response_model=FingerprintActionResponse)
def fingerprint_standby() -> FingerprintActionResponse:
    return FingerprintService().standby()


@router.post("/wake", response_model=FingerprintActionResponse)
def fingerprint_wake() -> FingerprintActionResponse:
    return FingerprintService().wake()


@router.post("/enroll/{user_id}", response_model=FingerprintActionResponse)
def enroll_fingerprint(user_id: str, timeout: int = Query(default=60, ge=10, le=90)) -> FingerprintActionResponse:
    return FingerprintService().start_enrollment(user_id, timeout=timeout)


@router.get("/enroll/{user_id}/{job_id}", response_model=FingerprintActionResponse)
def fingerprint_enrollment_progress(user_id: str, job_id: str) -> FingerprintActionResponse:
    return FingerprintService().enrollment_progress(user_id, job_id)


@router.delete("/{user_id}", response_model=FingerprintActionResponse)
def delete_fingerprint(user_id: str) -> FingerprintActionResponse:
    return FingerprintService().delete_user(user_id)
