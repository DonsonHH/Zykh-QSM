from __future__ import annotations

from fastapi import APIRouter

from ..schemas.settings import BasicSettingsResponse, BasicSettingsUpdateRequest
from ..services.settings_service import SettingsService


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/basic", response_model=BasicSettingsResponse)
def get_basic_settings() -> BasicSettingsResponse:
    return SettingsService().get()


@router.patch("/basic", response_model=BasicSettingsResponse)
def update_basic_settings(request: BasicSettingsUpdateRequest) -> BasicSettingsResponse:
    return SettingsService().update(request)
