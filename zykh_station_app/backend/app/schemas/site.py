from __future__ import annotations

from pydantic import BaseModel, Field


class SiteProfile(BaseModel):
    station_name: str = Field(default="偏远社区康护站")
    service_name: str = Field(default="村镇智慧用药服务点")
    location: str = Field(default="本地服务站")
    manager: str = Field(default="值守人员")
    network_mode: str = Field(default="weak")
    ai_mode: str = Field(default="rules")
    sync_status: str = Field(default="synced")


class SiteUpdate(BaseModel):
    station_name: str | None = None
    service_name: str | None = None
    location: str | None = None
    manager: str | None = None
    network_mode: str | None = None
    ai_mode: str | None = None
    sync_status: str | None = None
