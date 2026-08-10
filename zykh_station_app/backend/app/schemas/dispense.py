from __future__ import annotations

from pydantic import BaseModel, Field


class DispenseConfirmRequest(BaseModel):
    medicine_id: str
    slot: str
    quantity: int = Field(ge=1)
    reason: str
    confirmed_safety_notice: bool
    confirm_real_dispense: bool = False
    target_user_id: str = ""
    target_user_name: str = "家庭成员"
    verification_method: str = "manual"
    verification_score: float | None = None
    today_plan_id: str = ""
    archive_identity_snapshot: bool = False
    expected_review_fingerprint: str = ""


class DispenseOpenRequest(BaseModel):
    slot: int = Field(ge=1, le=23)
    quantity: int = Field(default=1, ge=1)
    reason: str = "现场开柜确认"
    confirmed_open: bool = False
    medicine_id: str | None = None
    target_user_id: str = ""
    target_user_name: str = ""


class DispenseConfirmResponse(BaseModel):
    ok: bool
    dry_run: bool
    message: str
    record_id: str | None = None
    qsm_detail: str | None = None
    result_unknown: bool = False


class DispenseOpenResponse(BaseModel):
    ok: bool
    dry_run: bool
    slot: int
    message: str
    qsm_detail: str | None = None


class DispenseRecord(BaseModel):
    id: str
    medicine_id: str
    medicine_name: str
    slot: str
    hardware_slot: int = 0
    quantity: int
    unit: str
    reason: str
    dry_run: bool
    message: str
    qsm_ok: bool = False
    qsm_detail: str = ""
    target_user_id: str = ""
    target_user_name: str = "家庭成员"
    verification_method: str = "manual"
    verification_score: float | None = None
    target_user_type: str = "registered"
    today_plan_id: str = ""
    created_at: str


class DispenseRecordsResponse(BaseModel):
    ok: bool = True
    records: list[DispenseRecord]
