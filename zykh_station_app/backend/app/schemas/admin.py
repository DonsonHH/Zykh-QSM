from __future__ import annotations

from pydantic import BaseModel, Field

from .inquiry import InquirySessionResponse
from .medicine import Medicine, MedicineUpdateRequest
from .records import (
    ServiceUser,
    ServiceUserCreateRequest,
    ServiceUserUpdateRequest,
    TodayPlan,
    TodayPlanCreateRequest,
    TodayPlanUpdateRequest,
)


class AdminSessionRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=32)


class AdminSessionResponse(BaseModel):
    ok: bool = True
    token: str
    expires_at: str
    expires_in_seconds: int


class AdminAuditRecord(BaseModel):
    id: str
    created_at: str
    actor: str
    action: str
    target: str
    result: str
    detail: str


class AdminDispenseArchive(BaseModel):
    id: str
    dispense_record_id: str
    target_user_name: str
    medicine_name: str
    captured_at: str
    status: str
    thumbnail_data_url: str = ""
    error_message: str = ""


class AdminOverviewResponse(BaseModel):
    ok: bool = True
    generated_at: str
    host: dict[str, object]
    counts: dict[str, int]
    devices: dict[str, object]
    network: dict[str, object]
    recent_audit: list[AdminAuditRecord]
    recent_dispense_archives: list[AdminDispenseArchive] = Field(default_factory=list)


class AdminLogSource(BaseModel):
    id: str
    label: str
    available: bool
    size: int = 0


class AdminLogsResponse(BaseModel):
    ok: bool = True
    source: str
    label: str
    lines: list[str]
    updated_at: str
    sources: list[AdminLogSource]


class AdminInquiryHistoryResponse(BaseModel):
    ok: bool = True
    sessions: list[InquirySessionResponse]
    repeated_question_sessions: int = 0


class AdminSystemActionRequest(BaseModel):
    action: str
    confirmation: str = ""


class AdminActionResponse(BaseModel):
    ok: bool
    accepted: bool = False
    action: str
    message: str
    detail: str = ""


class AdminUsersResponse(BaseModel):
    ok: bool = True
    users: list[ServiceUser]
    biometrics: dict[str, dict[str, object]] = Field(default_factory=dict)


class AdminUserCreateRequest(ServiceUserCreateRequest):
    pass


class AdminUserUpdateRequest(ServiceUserUpdateRequest):
    pass


class AdminMedicinesResponse(BaseModel):
    ok: bool = True
    medicines: list[Medicine]


class AdminMedicineUpdateRequest(MedicineUpdateRequest):
    pass


class AdminTodayPlansResponse(BaseModel):
    ok: bool = True
    plans: list[TodayPlan]
    users: list[ServiceUser]
    medicines: list[Medicine]


class AdminTodayPlanCreateRequest(TodayPlanCreateRequest):
    pass


class AdminTodayPlanUpdateRequest(TodayPlanUpdateRequest):
    pass


class AdminCabinetOpenRequest(BaseModel):
    confirmation: str
    reason: str = "管理员调试开柜"


class AdminConfirmationRequest(BaseModel):
    confirmation: str


class AdminBiometricResponse(BaseModel):
    ok: bool
    status: str
    message: str
    user: ServiceUser | None = None
    job_id: str | None = None
    event: str | None = None
