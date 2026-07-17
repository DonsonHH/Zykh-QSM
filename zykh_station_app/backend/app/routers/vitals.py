from __future__ import annotations

from ..routers.qsm import qsm_vitals
from ..services.qsm_client import QsmClient

from fastapi import APIRouter

from ..schemas.qsm import QsmVitalsResponse

router = APIRouter(prefix="/api/vitals", tags=["vitals"])


@router.post("/read-all", response_model=QsmVitalsResponse)
def read_all_vitals() -> QsmVitalsResponse:
    return qsm_vitals(full=True)


@router.post("/prepare")
def prepare_vitals() -> dict[str, object]:
    return QsmClient().prepare_vitals()
