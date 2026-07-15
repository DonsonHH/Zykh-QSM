from __future__ import annotations

from pydantic import BaseModel


class DeviceCheckResponse(BaseModel):
    ok: bool = True
    qsm_mode: str
    qsm_connected: bool
    qsm_base_url: str
    qsm_status_ok: bool
    vitals_ok: bool
    local_camera_ok: bool
    local_camera_mode: str
    local_camera_status: str
    local_ai_ok: bool
    local_ai_model: str
    local_ai_status: str
    dispense_dry_run: bool
    errors: list[str]
    warnings: list[str]
    recommendations: list[str]
