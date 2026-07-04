from __future__ import annotations

from pydantic import BaseModel, Field


class SiteProfile(BaseModel):
    station_name: str = Field(default="智药康护家用终端")
    service_name: str = Field(default="偏远家庭弱网用药服务")
    location: str = Field(default="家庭药柜")
    manager: str = Field(default="家庭成员")
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
