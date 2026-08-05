from __future__ import annotations

from ..routers.qsm import qsm_vitals
from ..modules.vitals_session import VitalsSessionModule, VitalsSessionNotFound

from fastapi import APIRouter, HTTPException

from ..schemas.qsm import QsmVitalsResponse, VitalsSessionResponse, VitalsSessionStartRequest

router = APIRouter(prefix="/api/vitals", tags=["vitals"])


@router.post("/read-all", response_model=QsmVitalsResponse)
def read_all_vitals() -> QsmVitalsResponse:
    return qsm_vitals(full=True)


@router.post("/prepare")
def prepare_vitals() -> dict[str, object]:
    return VitalsSessionModule().prepare()


@router.post("/session/start", response_model=VitalsSessionResponse)
def start_vitals_session(
    request: VitalsSessionStartRequest | None = None,
) -> VitalsSessionResponse:
    request = request or VitalsSessionStartRequest()
    return VitalsSessionModule().start(
        replace_active=request.replace_active
    )


@router.get("/session/{session_id}", response_model=VitalsSessionResponse)
def get_vitals_session(session_id: str) -> VitalsSessionResponse:
    try:
        return VitalsSessionModule().get(session_id)
    except VitalsSessionNotFound:
        raise HTTPException(status_code=404, detail="未找到体征测量会话。")


@router.post("/session/{session_id}/cancel", response_model=VitalsSessionResponse)
def cancel_vitals_session(session_id: str) -> VitalsSessionResponse:
    return VitalsSessionModule().cancel(session_id)
