from __future__ import annotations

from pydantic import BaseModel, Field


class BasicSettings(BaseModel):
    wifi_enabled: bool
    sim_enabled: bool
    network_mode: str
    speaker_volume: int = Field(ge=0, le=255)
    microphone_volume: int = Field(ge=0, le=100)
    display_brightness: int = Field(ge=20, le=100)
    idle_timeout_seconds: int = Field(ge=0, le=3600)
    wifi_ssid: str = ""
    sim_connected: bool = False
    microphone_available: bool = False


class BasicSettingsResponse(BaseModel):
    ok: bool = True
    settings: BasicSettings
    warnings: list[str] = Field(default_factory=list)


class BasicSettingsUpdateRequest(BaseModel):
    wifi_enabled: bool | None = None
    sim_enabled: bool | None = None
    network_mode: str | None = None
    speaker_volume: int | None = Field(default=None, ge=0, le=255)
    microphone_volume: int | None = Field(default=None, ge=0, le=100)
    display_brightness: int | None = Field(default=None, ge=20, le=100)
    idle_timeout_seconds: int | None = Field(default=None, ge=0, le=3600)
