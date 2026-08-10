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
    target_user_type: str = "registered"


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
    medical_conditions: list[dict[str, object]] = Field(default_factory=list)
    current_medications: list[dict[str, object]] = Field(default_factory=list)
    allergy_facts: list[dict[str, object]] = Field(default_factory=list)
    safety_profile_revision: int = 1
    safety_profile_updated_at: str = ""
    persona_generation: str = ""
    archived: bool = False


class ServiceUsersResponse(BaseModel):
    ok: bool = True
    users: list[ServiceUser]


class ServiceUserInquiryHistoryItem(BaseModel):
    session_id: str
    happened_at: str
    title: str
    case_summary: str
    risk_level: str
    risk_label: str
    risk_reasons: list[str] = Field(default_factory=list)
    outcome: str
    no_medicine_reason: str = ""
    final_medicine_summary: str = ""


class ServiceUserInquiryHistoryResponse(BaseModel):
    ok: bool = True
    user_id: str
    inquiries: list[ServiceUserInquiryHistoryItem]
    next_cursor: str | None = None


class ServiceUserCreateRequest(BaseModel):
    name: str
    age: int = 0
    profile: str = "待补充"
    allergies: str = ""
    note: str = "AI问询新建"
    status: str = "待完善"
    medical_conditions: list[dict[str, object]] = Field(default_factory=list)
    current_medications: list[dict[str, object]] = Field(default_factory=list)
    allergy_facts: list[dict[str, object]] = Field(default_factory=list)


class ServiceUserUpdateRequest(BaseModel):
    name: str | None = None
    age: int | None = None
    profile: str | None = None
    allergies: str | None = None
    note: str | None = None
    status: str | None = None
    medical_conditions: list[dict[str, object]] | None = None
    current_medications: list[dict[str, object]] | None = None
    allergy_facts: list[dict[str, object]] | None = None
    archived: bool | None = None


class TodayPlan(BaseModel):
    id: str
    time: str
    timing_label: str = ""
    medicine_id: str
    medicine: str
    service_user_id: str
    persona_generation: str = ""
    status: str
    target_user: str
    dose: str = "按说明"
    updated_at: str = ""
    schedule_type: str = "daily"
    interval_days: int = 1
    weekdays: list[int] = Field(default_factory=list)
    start_date: str = ""
    last_action_date: str = ""
    due_today: bool = True
    next_due_date: str = ""
    frequency_label: str = "每天"


class TodayPlanCreateRequest(BaseModel):
    time: str = Field(min_length=5, max_length=5)
    timing_label: str = Field(default="", max_length=12)
    medicine_id: str = Field(min_length=1, max_length=100)
    service_user_id: str = Field(min_length=1, max_length=100)
    dose: str = Field(default="按说明", max_length=40)
    status: str = Field(default="待执行", max_length=20)
    schedule_type: str = Field(default="daily", max_length=20)
    interval_days: int = Field(default=1, ge=1, le=30)
    weekdays: list[int] = Field(default_factory=list)
    start_date: str = Field(default="", max_length=10)


class TodayPlanUpdateRequest(BaseModel):
    time: str | None = Field(default=None, min_length=5, max_length=5)
    timing_label: str | None = Field(default=None, max_length=12)
    medicine_id: str | None = Field(default=None, min_length=1, max_length=100)
    service_user_id: str | None = Field(default=None, min_length=1, max_length=100)
    dose: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=20)
    schedule_type: str | None = Field(default=None, max_length=20)
    interval_days: int | None = Field(default=None, ge=1, le=30)
    weekdays: list[int] | None = None
    start_date: str | None = Field(default=None, max_length=10)


class TodayPlansResponse(BaseModel):
    ok: bool = True
    plans: list[TodayPlan]
