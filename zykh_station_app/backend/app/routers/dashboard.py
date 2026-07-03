from __future__ import annotations

from fastapi import APIRouter

from ..schemas.dashboard import DashboardPayload
from ..services.dashboard_service import DashboardService

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardPayload)
def dashboard() -> DashboardPayload:
    return DashboardService().get_dashboard()
