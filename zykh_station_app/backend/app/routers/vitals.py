from __future__ import annotations

from ..routers.qsm import qsm_vitals

from fastapi import APIRouter

from ..schemas.qsm import QsmVitalsResponse

router = APIRouter(prefix="/api/vitals", tags=["vitals"])


@router.post("/read-all", response_model=QsmVitalsResponse)
def read_all_vitals() -> QsmVitalsResponse:
    return qsm_vitals()
