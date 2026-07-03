from __future__ import annotations

from fastapi import APIRouter

from ..schemas.status import ApiStatus
from ..services.dashboard_service import DashboardService

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status", response_model=ApiStatus)
def status() -> ApiStatus:
    return DashboardService().get_status()
