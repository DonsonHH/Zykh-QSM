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
    fingerprint_ok: bool
    fingerprint_status: str
    fingerprint_bound_users: int
    offline_tts_ok: bool = False
    offline_tts_engine: str = ""
    offline_tts_model: str = ""
    offline_tts_status: str = "unavailable"
    # Compatibility fields for older clients. The current UI does not expose a local LLM.
    local_ai_ok: bool = False
    local_ai_model: str = ""
    local_ai_status: str = "disabled"
    dispense_dry_run: bool
    errors: list[str]
    warnings: list[str]
    recommendations: list[str]
