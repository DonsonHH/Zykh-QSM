from __future__ import annotations

from fastapi import APIRouter

from ..schemas.site import SiteProfile, SiteUpdate
from ..services.station_service import StationService

router = APIRouter(prefix="/api/site", tags=["site"])


@router.get("", response_model=SiteProfile)
def get_site() -> SiteProfile:
    return StationService().get_site()


@router.post("", response_model=SiteProfile)
def save_site(update: SiteUpdate) -> SiteProfile:
    return StationService().save_site(update)
