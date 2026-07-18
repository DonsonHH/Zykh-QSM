from __future__ import annotations

from typing import Any, Literal

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
    match_reason: str = ""


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


InquiryStage = Literal["symptoms", "duration", "used_medicines", "allergies", "vitals", "result", "escalated"]
InquiryNextAction = Literal["ask", "measure_vitals", "show_recommendation", "escalate"]
InquiryMessageRole = Literal["assistant", "user", "system"]


class InquirySessionCreateRequest(BaseModel):
    service_user_id: str = ""
    guest_name: str = "访客"


class InquiryTurnRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=600)


class InquiryVitalsRequest(BaseModel):
    temperature: float = Field(gt=0, lt=50)
    heart_rate: int = Field(gt=0, lt=260)
    spo2: int = Field(gt=0, le=100)
    systolic_pressure: int | None = None
    diastolic_pressure: int | None = None
    respiratory_rate: int | None = None
    hrv_sdnn: int | None = None
    hrv_rmssd: int | None = None
    measured_at: str = ""


class InquiryMessage(BaseModel):
    id: str
    role: InquiryMessageRole
    content: str
    source: str = ""
    created_at: str


class InquiryExtractedInformation(BaseModel):
    symptom_dimensions: list[str] = Field(default_factory=list)
    dimension_evidence: dict[str, str] = Field(default_factory=dict)
    symptoms_text: str = ""
    duration: str = ""
    used_medicines: str = ""
    allergy_or_contraindication: str = ""
    confidence: float = 0.0


class InquirySessionResponse(BaseModel):
    session_id: str
    user_id: str = ""
    user_name: str
    user_age: int = 0
    user_profile: str = ""
    user_allergies: str = ""
    stage: InquiryStage
    reply: str
    source: str = "rules_fallback"
    extracted_information: InquiryExtractedInformation = Field(default_factory=InquiryExtractedInformation)
    vitals: dict[str, Any] | None = None
    risk_level: RiskLevel | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    next_action: InquiryNextAction
    primary_candidate: CandidateMedicine | None = None
    alternative_candidate: CandidateMedicine | None = None
    can_view_medicines: bool = False
    messages: list[InquiryMessage] = Field(default_factory=list)
    title: str = "新问询"
    created_at: str
    updated_at: str
