from __future__ import annotations

from ..routers.qsm import qsm_vitals
from ..services.qsm_client import QsmClient

from fastapi import APIRouter, HTTPException

from ..schemas.qsm import QsmVitalsResponse, VitalsSessionResponse

router = APIRouter(prefix="/api/vitals", tags=["vitals"])


@router.post("/read-all", response_model=QsmVitalsResponse)
def read_all_vitals() -> QsmVitalsResponse:
    return qsm_vitals(full=True)


@router.post("/prepare")
def prepare_vitals() -> dict[str, object]:
    return QsmClient().prepare_vitals()


@router.post("/session/start", response_model=VitalsSessionResponse)
def start_vitals_session() -> VitalsSessionResponse:
    return VitalsSessionResponse(**QsmClient().start_vitals_session())


@router.get("/session/{session_id}", response_model=VitalsSessionResponse)
def get_vitals_session(session_id: str) -> VitalsSessionResponse:
    result = QsmClient().get_vitals_session(session_id)
    if not result.get("session_id"):
        raise HTTPException(status_code=404, detail="未找到体征测量会话。")
    return VitalsSessionResponse(**result)


@router.post("/session/{session_id}/cancel", response_model=VitalsSessionResponse)
def cancel_vitals_session(session_id: str) -> VitalsSessionResponse:
    return VitalsSessionResponse(**QsmClient().cancel_vitals_session(session_id))
