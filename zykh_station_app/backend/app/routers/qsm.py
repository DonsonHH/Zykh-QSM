from __future__ import annotations

from fastapi import APIRouter

from ..schemas.qsm import QsmStatus
from ..services.qsm_client import QsmClient

router = APIRouter(prefix="/api/qsm", tags=["qsm"])


@router.get("/status", response_model=QsmStatus)
def qsm_status() -> QsmStatus:
    return QsmClient().get_qsm_status()
