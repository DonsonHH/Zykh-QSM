from __future__ import annotations

from fastapi import APIRouter

from ..schemas.device import DeviceCheckResponse
from ..services.device_check_service import DeviceCheckService

router = APIRouter(prefix="/api/device", tags=["device"])


@router.get("/check", response_model=DeviceCheckResponse)
def device_check() -> DeviceCheckResponse:
    return DeviceCheckService().check()
