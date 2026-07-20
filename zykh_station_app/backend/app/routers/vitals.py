from __future__ import annotations

from uuid import uuid4

from ..routers.qsm import qsm_vitals
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..repositories.sync_repository import SyncRepository
from ..repositories.vitals_repository import VitalsRecord, VitalsRepository
from ..services.qsm_client import QsmClient

from fastapi import APIRouter, HTTPException

from ..db import now_text
from ..schemas.qsm import QsmVitalsResponse, VitalsSessionResponse, VitalsSessionStartRequest

router = APIRouter(prefix="/api/vitals", tags=["vitals"])


@router.post("/read-all", response_model=QsmVitalsResponse)
def read_all_vitals() -> QsmVitalsResponse:
    return qsm_vitals(full=True)


@router.post("/prepare")
def prepare_vitals() -> dict[str, object]:
    return QsmClient().prepare_vitals()


@router.post("/session/start", response_model=VitalsSessionResponse)
def start_vitals_session(
    request: VitalsSessionStartRequest | None = None,
) -> VitalsSessionResponse:
    request = request or VitalsSessionStartRequest()
    return VitalsSessionResponse(
        **QsmClient().start_vitals_session(replace_active=request.replace_active)
    )


@router.get("/session/{session_id}", response_model=VitalsSessionResponse)
def get_vitals_session(session_id: str) -> VitalsSessionResponse:
    result = QsmClient().get_vitals_session(session_id)
    if not result.get("session_id"):
        raise HTTPException(status_code=404, detail="未找到体征测量会话。")
    response = VitalsSessionResponse(**result)
    _persist_completed_session(response)
    return response


@router.post("/session/{session_id}/cancel", response_model=VitalsSessionResponse)
def cancel_vitals_session(session_id: str) -> VitalsSessionResponse:
    return VitalsSessionResponse(**QsmClient().cancel_vitals_session(session_id))


def _persist_completed_session(response: VitalsSessionResponse) -> None:
    if response.status != "complete":
        return
    if response.heart_rate is None or response.spo2 is None or response.temperature is None:
        return
    measured_at = response.measured_at or response.updated_at or now_text()
    record = VitalsRecord(
        id=f"vitals-session-{response.session_id}",
        temperature=response.temperature,
        heart_rate=response.heart_rate,
        spo2=response.spo2,
        systolic_pressure=response.systolic_pressure,
        diastolic_pressure=response.diastolic_pressure,
        respiratory_rate=response.respiratory_rate,
        microcirculation=response.microcirculation,
        fatigue=response.fatigue,
        rr_interval=response.rr_interval,
        hrv_sdnn=response.hrv_sdnn,
        hrv_rmssd=response.hrv_rmssd,
        body_temperature=response.body_temperature,
        ambient_temperature=response.ambient_temperature,
        status="available",
        source=response.source or response.mode,
        sensor_model=response.source or "",
        error_message="",
        measured_at=measured_at,
    )
    if not VitalsRepository().append_once(record):
        return
    SyncRepository().mark_pending()
    DeviceActionRepository().append(
        DeviceActionRecord(
            id=f"device-{uuid4().hex[:12]}",
            created_at=measured_at,
            type="体征读取",
            title=f"心率 {response.heart_rate}次/分，血氧 {response.spo2}%",
            description=f"额温 {response.temperature:.1f}℃，体征测量已完成。",
            status="已记录",
        )
    )
