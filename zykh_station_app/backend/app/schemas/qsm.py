from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QsmStatus(BaseModel):
    ok: bool
    mode: str
    connected: bool
    base_url: str
    device_status: str
    vitals_status: str
    camera_status: str
    dispense_status: str
    error_message: str | None = None
    status_label: str
    vitals: dict[str, object]
    devices: dict[str, str]
    detail: str = ""


class QsmVitalsResponse(BaseModel):
    ok: bool
    mode: str
    status: str
    temperature: float | None = None
    heart_rate: int | None = None
    spo2: int | None = None
    temperature_source: str | None = None
    heart_rate_source: str | None = None
    spo2_source: str | None = None
    spo2_demo_fallback: bool | None = None
    systolic_pressure: int | None = None
    diastolic_pressure: int | None = None
    respiratory_rate: int | None = None
    microcirculation: int | None = None
    fatigue: int | None = None
    rr_interval: int | None = None
    hrv_sdnn: int | None = None
    hrv_rmssd: int | None = None
    body_temperature: float | None = None
    ambient_temperature: float | None = None
    reference_ready: bool | None = None
    finger_detected: bool | None = None
    quality: str | None = None
    message: str | None = None
    sample_count: int | None = None
    partial: bool | None = None
    source: str | None = None
    sensor_model: str | None = None
    measured_at: str
    error_message: str | None = None


class VitalsSessionResponse(BaseModel):
    ok: bool
    mode: str = "real"
    session_id: str
    status: str
    hardware_started: bool = False
    elapsed_seconds: float | None = None
    temperature: float | None = None
    heart_rate: int | None = None
    spo2: int | None = None
    temperature_source: str | None = None
    heart_rate_source: str | None = None
    spo2_source: str | None = None
    spo2_demo_fallback: bool | None = None
    systolic_pressure: int | None = None
    diastolic_pressure: int | None = None
    respiratory_rate: int | None = None
    microcirculation: int | None = None
    fatigue: int | None = None
    rr_interval: int | None = None
    hrv_sdnn: int | None = None
    hrv_rmssd: int | None = None
    body_temperature: float | None = None
    ambient_temperature: float | None = None
    reference_ready: bool | None = None
    finger_detected: bool | None = None
    quality: str | None = None
    message: str | None = None
    sample_count: int | None = None
    valid_frame_count: int | None = None
    contact_frame_count: int | None = None
    heart_rate_frame_count: int | None = None
    spo2_frame_count: int | None = None
    first_heart_rate_frame: int | None = None
    first_spo2_frame: int | None = None
    stable_core: bool | None = None
    communication_status: str | None = None
    no_contact_grace_applied: bool | None = None
    start_retried: bool | None = None
    start_recovery_mode: str | None = None
    stabilization_extended: bool | None = None
    spo2_stabilization_extended: bool | None = None
    prewarmed: bool | None = None
    prewarm_age: float | None = None
    minimum_measurement_seconds: float | None = None
    failure_reason: str | None = None
    demo_fallback_reason: str | None = None
    completion_reason: str | None = None
    cancel_reason: str | None = None
    source: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    measured_at: str | None = None
    error_message: str | None = None
    historical_fallback: bool = False
    historical_temperature: float | None = None
    historical_heart_rate: int | None = None
    historical_spo2: int | None = None
    historical_source: str | None = None
    historical_measured_at: str | None = None
    source_route: Literal["HOME", "INQUIRY"] = "HOME"
    inquiry_session_id: str = ""
    attribution_source: Literal["UNREGISTERED", "INQUIRY_SESSION"] = "UNREGISTERED"
    service_user_id: str = ""
    service_user_name_snapshot: str = ""
    persona_generation: str = ""


class VitalsSessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replace_active: bool = True
    source_route: Literal["HOME", "INQUIRY"] = "HOME"
    inquiry_session_id: str = ""


class QsmCameraRecognition(BaseModel):
    medicine_id: str | None = None
    name: str
    match_percent: int
    barcode: str
    spec: str
    quantity: str
    expire_date: str
    slot: str


class QsmCameraCaptureResponse(BaseModel):
    ok: bool
    mode: str
    status: str
    image_available: bool
    image_path: str | None = None
    image_url: str | None = None
    mock_recognition_result: QsmCameraRecognition | None = None
    error_message: str | None = None


class QsmDryRunRequest(BaseModel):
    slot: str
    medicine_id: str
    quantity: int = Field(ge=1)
    reason: str


class QsmDryRunResponse(BaseModel):
    ok: bool
    dry_run: bool = True
    message: str
    record_id: str | None = None


class QsmCapabilitiesResponse(BaseModel):
    ok: bool = True
    camera: str
    vitals: str
    dispense: str
    voice: str
    qsm_connected: bool
    mode: str


class QsmCabinetLightResponse(BaseModel):
    ok: bool
    mode: str
    result: str
    status: str
    message: str
    cabinet_id: int | None = Field(default=None, ge=1, le=3)
    result_unknown: bool = False
    retry_safe: bool = True
