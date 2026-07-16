from __future__ import annotations

from pydantic import BaseModel, Field


class RecordsSummary(BaseModel):
    today_service_users: int
    pending_sync_count: int
    local_record_count: int
    today_plan_count: int


class RecentRecord(BaseModel):
    id: str
    time: str
    type: str
    title: str
    description: str
    target_user: str
    status: str
    sync_status: str


class RecordsSummaryResponse(BaseModel):
    ok: bool = True
    summary: RecordsSummary


class RecentRecordsResponse(BaseModel):
    ok: bool = True
    records: list[RecentRecord]


class ServiceUser(BaseModel):
    id: str
    name: str
    age: int
    profile: str
    allergies: str = ""
    note: str
    status: str


class ServiceUsersResponse(BaseModel):
    ok: bool = True
    users: list[ServiceUser]


class ServiceUserCreateRequest(BaseModel):
    name: str
    age: int = 0
    profile: str = "待补充"
    allergies: str = ""
    note: str = "AI问询新建"
    status: str = "待完善"


class ServiceUserUpdateRequest(BaseModel):
    name: str | None = None
    age: int | None = None
    profile: str | None = None
    allergies: str | None = None
    note: str | None = None
    status: str | None = None


class TodayPlan(BaseModel):
    id: str
    time: str
    medicine_id: str
    medicine: str
    service_user_id: str
    status: str
    target_user: str
    dose: str = "按说明"
    updated_at: str = ""


class TodayPlanCreateRequest(BaseModel):
    time: str = Field(min_length=5, max_length=5)
    medicine_id: str = Field(min_length=1, max_length=100)
    service_user_id: str = Field(min_length=1, max_length=100)
    dose: str = Field(default="按说明", max_length=40)
    status: str = Field(default="待执行", max_length=20)


class TodayPlanUpdateRequest(BaseModel):
    time: str | None = Field(default=None, min_length=5, max_length=5)
    medicine_id: str | None = Field(default=None, min_length=1, max_length=100)
    service_user_id: str | None = Field(default=None, min_length=1, max_length=100)
    dose: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=20)


class TodayPlansResponse(BaseModel):
    ok: bool = True
    plans: list[TodayPlan]
