from __future__ import annotations

from pydantic import BaseModel, Field


class DispenseConfirmRequest(BaseModel):
    medicine_id: str
    slot: str
    quantity: int = Field(ge=1)
    reason: str
    confirmed_safety_notice: bool


class DispenseConfirmResponse(BaseModel):
    ok: bool
    dry_run: bool
    message: str
    record_id: str | None = None
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
    created_at: str


class DispenseRecordsResponse(BaseModel):
    ok: bool = True
    records: list[DispenseRecord]
