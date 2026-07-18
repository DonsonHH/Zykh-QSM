from __future__ import annotations

from pydantic import BaseModel, Field


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
    source: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    measured_at: str | None = None
    error_message: str | None = None


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
