from __future__ import annotations

from fastapi import APIRouter

from .. import db
from ..config import settings

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
    }
