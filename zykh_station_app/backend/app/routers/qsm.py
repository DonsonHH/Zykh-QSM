from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..config import real_dispense_enabled, settings
from ..db import now_text
from ..repositories.device_action_repository import DeviceActionRecord, DeviceActionRepository
from ..repositories.vitals_repository import VitalsRecord, VitalsRepository
from ..schemas.dispense import DispenseConfirmRequest
from ..schemas.qsm import (
    QsmCameraCaptureResponse,
    QsmCapabilitiesResponse,
    QsmDryRunRequest,
    QsmDryRunResponse,
    QsmStatus,
    QsmVitalsResponse,
)
from ..services.dispense_service import DispenseError, DispenseService
from ..services.local_camera import LocalCameraService
from ..services.qsm_client import QsmClient

router = APIRouter(prefix="/api/qsm", tags=["qsm"])


@router.get("/status", response_model=QsmStatus)
def qsm_status() -> QsmStatus:
    return QsmClient().get_qsm_status()


@router.get("/vitals", response_model=QsmVitalsResponse)
def qsm_vitals() -> QsmVitalsResponse:
    client = QsmClient()
    vitals = client.read_vitals()
    source = str(vitals.get("source", "fallback"))
    status = _vitals_status(client.mode, source)
    response = QsmVitalsResponse(
        ok=status != "unavailable",
        mode=client.mode,
        status=status,
        temperature=_float_or_none(vitals.get("temperature_c")),
        heart_rate=_int_or_none(vitals.get("heart_rate")),
        spo2=_int_or_none(vitals.get("spo2")),
        measured_at=now_text(),
        error_message=vitals.get("error_message") if isinstance(vitals.get("error_message"), str) else None,
    )
    VitalsRepository().append(
        VitalsRecord(
            id=f"vitals-{uuid4().hex[:12]}",
            temperature=response.temperature,
            heart_rate=response.heart_rate,
            spo2=response.spo2,
            status=response.status,
            source=str(vitals.get("source", client.mode)),
            error_message=response.error_message or "",
            measured_at=response.measured_at,
        )
    )
    DeviceActionRepository().append(
        DeviceActionRecord(
            id=f"device-{uuid4().hex[:12]}",
            created_at=response.measured_at,
            type="体征读取",
            title=_vitals_record_title(response),
            description=_vitals_record_description(response),
            status="已记录" if response.ok else "暂不可用",
        )
    )
    return response


@router.post("/camera/capture", response_model=QsmCameraCaptureResponse)
def qsm_camera_capture() -> QsmCameraCaptureResponse:
    client = QsmClient()
    payload = LocalCameraService().capture()
    response = QsmCameraCaptureResponse(
        ok=bool(payload.get("ok")),
        mode=str(payload.get("mode", client.mode)),
        status=str(payload.get("status", "unavailable")),
        image_available=bool(payload.get("image_available")),
        image_path=payload.get("image_path"),
        image_url=payload.get("image_url"),
        mock_recognition_result=None,
        error_message=payload.get("error_message"),
    )
    DeviceActionRepository().append(
        DeviceActionRecord(
            id=f"device-{uuid4().hex[:12]}",
            created_at=now_text(),
            type="药品扫码",
            title=response.mock_recognition_result.name if response.mock_recognition_result else "摄像头识别",
            description=_camera_record_description(response),
            status="已记录" if response.ok else "暂不可用",
        )
    )
    return response


@router.post("/dispense/dry-run", response_model=QsmDryRunResponse)
def qsm_dispense_dry_run(request: QsmDryRunRequest) -> QsmDryRunResponse:
    client = QsmClient()
    client.dispense(request.slot, request.quantity, dry_run=True)
    try:
        result = DispenseService().confirm(
            DispenseConfirmRequest(
                medicine_id=request.medicine_id,
                slot=request.slot,
                quantity=request.quantity,
                reason=request.reason,
                confirmed_safety_notice=True,
            ),
            force_dry_run=True,
        )
    except DispenseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    qsm = client.get_qsm_status()
    message = result.message
    if qsm.mode == "real" and not qsm.connected:
        message = "外设暂不可用，已完成本地 dry-run 记录。"
    return QsmDryRunResponse(ok=result.ok, dry_run=True, message=message, record_id=result.record_id)


@router.get("/capabilities", response_model=QsmCapabilitiesResponse)
def qsm_capabilities() -> QsmCapabilitiesResponse:
    client = QsmClient()
    qsm = client.get_qsm_status()
    return QsmCapabilitiesResponse(
        camera=LocalCameraService().capabilities(),
        vitals="mock" if client.mode != "real" else ("available" if qsm.connected else "unavailable"),
        dispense="available" if real_dispense_enabled() and qsm.connected else "dry_run",
        voice=qsm.devices.get("voice", "unavailable"),
        qsm_connected=qsm.connected,
        mode=client.mode,
    )


def _vitals_status(mode: str, source: str) -> str:
    if mode != "real":
        return "partial"
    return "available" if source == "real" else "unavailable"


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _vitals_record_title(response: QsmVitalsResponse) -> str:
    if response.temperature is None:
        return "体征设备暂不可用"
    return f"体温 {response.temperature:.1f}℃"


def _vitals_record_description(response: QsmVitalsResponse) -> str:
    if response.status == "unavailable":
        return "体征读取未完成，已保留本地记录。"
    heart_rate = f"{response.heart_rate}次/分" if response.heart_rate is not None else "暂不可用"
    spo2 = f"{response.spo2}%" if response.spo2 is not None else "暂不可用"
    return f"心率 {heart_rate}，血氧 {spo2}。"


def _camera_record_description(response: QsmCameraCaptureResponse) -> str:
    if response.mock_recognition_result:
        item = response.mock_recognition_result
        return f"识别到 {item.name}，匹配度 {item.match_percent}%，仓位 {item.slot}。"
    if response.status == "unavailable":
        return "摄像头暂不可用，已保留本地记录。"
    return "完成本机摄像头入口检查。"
