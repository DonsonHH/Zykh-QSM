from __future__ import annotations

from fastapi import APIRouter

from .. import db
from ..config import real_dispense_enabled, settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    database = db.health_check()
    return {
        "ok": True,
        "app": settings.app_name,
        "database": database,
        "qsm_mode": settings.qsm_mode,
        "dry_run": settings.dispense_dry_run,
        "enable_real_dispense": settings.enable_real_dispense,
        "real_dispense_enabled": real_dispense_enabled(),
    }
