from __future__ import annotations

from fastapi import APIRouter, Query

from ..schemas.dashboard import DashboardPayload
from ..services.dashboard_service import DashboardService

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardPayload)
def dashboard(target_user: str | None = Query(default=None, max_length=80)) -> DashboardPayload:
    return DashboardService().get_dashboard(target_user=target_user)
