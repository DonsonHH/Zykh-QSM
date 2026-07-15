from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "emergency"]


class InquiryEvaluateRequest(BaseModel):
    symptoms_text: str = Field(min_length=1)
    duration: str = ""
    used_medicines: str = ""
    allergy_or_contraindication: str = ""
    scene_type: str = "家庭"
    include_vitals: bool = False


class CandidateMedicine(BaseModel):
    id: str
    name: str
    category: str
    slot: str
    stock: int
    unit: str
    safety_note: str


class InquiryResult(BaseModel):
    inquiry_id: str
    risk_level: RiskLevel
    risk_label: str
    symptoms_summary: str
    suggested_categories: list[str]
    candidate_medicines: list[CandidateMedicine]
    contraindication_warnings: list[str]
    safety_notice: str
    next_steps: list[str]
    can_proceed_to_dispense: bool
    created_at: str
    ai_source: str = "rules_fallback"
    ai_message: str = "安全规则核验"


class InquiryRecordResponse(BaseModel):
    ok: bool = True
    result: InquiryResult


class InquiryRecordsResponse(BaseModel):
    ok: bool = True
    records: list[InquiryResult]
