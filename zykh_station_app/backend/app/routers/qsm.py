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
from ..services.qsm_camera_service import QsmCameraService
from ..services.qsm_client import QsmClient

router = APIRouter(prefix="/api/qsm", tags=["qsm"])


@router.get("/status", response_model=QsmStatus)
def qsm_status() -> QsmStatus:
    return QsmClient().get_qsm_status()


@router.get("/vitals", response_model=QsmVitalsResponse)
def qsm_vitals(full: bool = False) -> QsmVitalsResponse:
    client = QsmClient()
    vitals = client.read_full_vitals() if full else client.read_vitals()
    source = str(vitals.get("source", "fallback"))
    status = _vitals_status(client.mode, source, vitals)
    response = QsmVitalsResponse(
        ok=status != "unavailable",
        mode=client.mode,
        status=status,
        temperature=_float_or_none(vitals.get("temperature_c")),
        heart_rate=_int_or_none(vitals.get("heart_rate")),
        spo2=_int_or_none(vitals.get("spo2")),
        systolic_pressure=_int_or_none(vitals.get("systolic_pressure")),
        diastolic_pressure=_int_or_none(vitals.get("diastolic_pressure")),
        respiratory_rate=_int_or_none(vitals.get("respiratory_rate")),
        microcirculation=_int_or_none(vitals.get("microcirculation")),
        fatigue=_int_or_none(vitals.get("fatigue")),
        rr_interval=_int_or_none(vitals.get("rr_interval")),
        hrv_sdnn=_int_or_none(vitals.get("hrv_sdnn")),
        hrv_rmssd=_int_or_none(vitals.get("hrv_rmssd")),
        body_temperature=_float_or_none(vitals.get("sensor_body_temperature")),
        ambient_temperature=_float_or_none(vitals.get("ambient_temperature")),
        reference_ready=_bool_or_none(vitals.get("reference_ready")),
        finger_detected=_bool_or_none(vitals.get("finger_detected")),
        quality=str(vitals.get("quality")) if vitals.get("quality") is not None else None,
        message=str(vitals.get("message")) if vitals.get("message") is not None else None,
        sample_count=_int_or_none(vitals.get("sample_count")),
        partial=_bool_or_none(vitals.get("partial")),
        source=str(vitals.get("source", client.mode)),
        sensor_model=_sensor_model(vitals),
        measured_at=now_text(),
        error_message=vitals.get("error_message") if isinstance(vitals.get("error_message"), str) else None,
    )
    VitalsRepository().append(
        VitalsRecord(
            id=f"vitals-{uuid4().hex[:12]}",
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
            status=response.status,
            source=str(vitals.get("source", client.mode)),
            sensor_model=response.sensor_model or "",
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
    payload = client.capture_camera()
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
        message = "外设暂不可用，已完成本地测试记录。"
    return QsmDryRunResponse(ok=result.ok, dry_run=True, message=message, record_id=result.record_id)


@router.get("/capabilities", response_model=QsmCapabilitiesResponse)
def qsm_capabilities() -> QsmCapabilitiesResponse:
    client = QsmClient()
    qsm = client.get_qsm_status()
    return QsmCapabilitiesResponse(
        camera=QsmCameraService().capabilities(),
        vitals="mock" if client.mode != "real" else ("available" if qsm.connected else "unavailable"),
        dispense="available" if real_dispense_enabled() and qsm.connected else "dry_run",
        voice=qsm.devices.get("voice", "unavailable"),
        qsm_connected=qsm.connected,
        mode=client.mode,
    )


def _vitals_status(mode: str, source: str, vitals: dict[str, object]) -> str:
    if mode != "real":
        return "partial"
    if source != "real":
        return "unavailable"
    if vitals.get("partial") is True:
        return "partial"
    if (
        vitals.get("finger_detected") is False
        and vitals.get("heart_rate") is None
        and vitals.get("spo2") is None
    ):
        return "awaiting_finger"
    return "available"


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


def _bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def _sensor_model(vitals: dict[str, object]) -> str | None:
    raw = vitals.get("raw")
    if not isinstance(raw, dict):
        return None
    sensors = raw.get("sensors")
    if not isinstance(sensors, dict):
        return None
    for sensor_name in ("uart_vitals", "integrated_vitals", "max30102"):
        sensor = sensors.get(sensor_name)
        if not isinstance(sensor, dict):
            continue
        data = sensor.get("data")
        if isinstance(data, dict) and data.get("source"):
            return str(data["source"])
    return None


def _vitals_record_title(response: QsmVitalsResponse) -> str:
    if response.heart_rate is not None or response.spo2 is not None:
        parts = []
        if response.heart_rate is not None:
            parts.append(f"心率 {response.heart_rate}次/分")
        if response.spo2 is not None:
            parts.append(f"血氧 {response.spo2}%")
        return "，".join(parts)
    if response.temperature is None:
        return "体征设备暂不可用"
    return f"体温 {response.temperature:.1f}℃"


def _vitals_record_description(response: QsmVitalsResponse) -> str:
    if response.status == "unavailable":
        return "体征读取未完成，已保留本地记录。"
    if response.finger_detected is False:
        return "未检测到手指或信号偏弱，请按引导重新放置手指后再测量。"
    heart_rate = f"{response.heart_rate}次/分" if response.heart_rate is not None else "暂不可用"
    spo2 = f"{response.spo2}%" if response.spo2 is not None else "暂不可用"
    pressure = ""
    if response.systolic_pressure is not None and response.diastolic_pressure is not None:
        pressure = f"，血压参考 {response.systolic_pressure}/{response.diastolic_pressure}mmHg"
    return f"心率 {heart_rate}，血氧 {spo2}{pressure}。"


def _camera_record_description(response: QsmCameraCaptureResponse) -> str:
    if response.mock_recognition_result:
        item = response.mock_recognition_result
        return f"识别到 {item.name}，匹配度 {item.match_percent}%，仓位 {item.slot}。"
    if response.status == "unavailable":
        return "摄像头暂不可用，已保留本地记录。"
    return "完成本机摄像头入口检查。"
