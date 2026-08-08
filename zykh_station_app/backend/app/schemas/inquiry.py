from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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
    indications: str = ""
    dosage: str = ""
    tags: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    active_ingredients: list[str] = Field(default_factory=list)
    review_fingerprint: str = ""
    match_reason: str = ""
    requires_existing_direction: bool = False


class TreatmentMedicine(CandidateMedicine):
    role: str = "主要对症"
    covered_symptoms: list[str] = Field(default_factory=list)
    recommended_usage: str = ""


class TreatmentOption(BaseModel):
    option_id: str
    label: str
    when: str
    medicines: list[TreatmentMedicine] = Field(default_factory=list)


class MedicineSafetyNotice(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=160)


class InquiryResult(BaseModel):
    inquiry_id: str
    risk_level: RiskLevel
    risk_label: str
    symptoms_summary: str
    suggested_categories: list[str]
    candidate_medicines: list[CandidateMedicine]
    contraindication_warnings: list[str]
    medication_safety_notices: list[MedicineSafetyNotice] = Field(default_factory=list)
    safety_notice: str
    next_steps: list[str]
    can_proceed_to_dispense: bool
    created_at: str
    ai_source: str = "rules_fallback"
    ai_message: str = "本地问询核验"


class InquiryRecordResponse(BaseModel):
    ok: bool = True
    result: InquiryResult


class InquiryRecordsResponse(BaseModel):
    ok: bool = True
    records: list[InquiryResult]


InquiryStage = Literal[
    "symptoms", "clarification", "duration", "used_medicines", "allergies", "vitals", "result", "escalated"
]
InquiryNextAction = Literal["ask", "measure_vitals", "show_recommendation", "escalate", "complete"]
InquiryMessageRole = Literal["assistant", "user", "system"]
InquiryModelAction = Literal["ask", "measure_vitals", "analyze", "escalate", "end"]
InquiryActionStatus = Literal["idle", "ready", "opening", "complete", "partial", "failed"]


class InquirySessionCreateRequest(BaseModel):
    service_user_id: str = ""
    guest_name: str = "访客"


class InquiryTurnRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=600)


class InquiryInformationRevisionRequest(BaseModel):
    main_complaint: str = Field(min_length=1, max_length=300)
    duration: str = Field(min_length=1, max_length=120)
    used_medicines: str = Field(min_length=1, max_length=180)
    allergy_or_contraindication: str = Field(min_length=1, max_length=180)
    finalize: bool = True


class InquiryVitalsRequest(BaseModel):
    status: Literal["complete", "failed", "cancelled"] = "complete"
    temperature: float | None = Field(default=None, gt=0, lt=50)
    heart_rate: int | None = Field(default=None, gt=0, lt=260)
    spo2: int | None = Field(default=None, gt=0, le=100)
    temperature_source: str | None = None
    heart_rate_source: str | None = None
    spo2_source: str | None = None
    spo2_demo_fallback: bool = False
    historical_fallback: bool = False
    systolic_pressure: int | None = None
    diastolic_pressure: int | None = None
    respiratory_rate: int | None = None
    hrv_sdnn: int | None = None
    hrv_rmssd: int | None = None
    measured_at: str = ""
    error_message: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def require_core_vitals_when_complete(self) -> "InquiryVitalsRequest":
        if self.status != "complete" and any(
            value is not None
            for value in (
                self.temperature,
                self.heart_rate,
                self.spo2,
                self.systolic_pressure,
                self.diastolic_pressure,
                self.respiratory_rate,
                self.hrv_sdnn,
                self.hrv_rmssd,
            )
        ):
            raise ValueError("非完成状态不得携带体征测量数值。")
        if self.status == "complete" and (
            self.spo2_demo_fallback or self.spo2_source == "demo_fallback"
        ):
            raise ValueError("演示血氧不得作为完成的问询体征保存。")
        if self.historical_fallback or any(
            source in {"history_fallback", "historical_fallback"}
            for source in (self.temperature_source, self.heart_rate_source, self.spo2_source)
        ):
            raise ValueError("历史体征不得作为本次问询体征保存。")
        if self.status == "complete" and (
            self.temperature is None or self.heart_rate is None or self.spo2 is None
        ):
            raise ValueError("测量完成时必须包含额温、心率和血氧。")
        if self.status == "complete" and (
            self.temperature_source != "gy614_sensor"
            or self.heart_rate_source != "uart8_sensor"
            or self.spo2_source != "uart8_sensor"
        ):
            raise ValueError("完成的问询体征必须包含本次设备实时来源。")
        return self


class InquiryMessage(BaseModel):
    id: str
    role: InquiryMessageRole
    content: str
    source: str = ""
    created_at: str


class InquiryObservation(BaseModel):
    concept: str = Field(min_length=1, max_length=80)
    status: Literal["present", "absent", "uncertain"] = "uncertain"
    evidence: str = Field(default="", max_length=180)
    source_turn: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)


class InquiryHistoryRelationship(BaseModel):
    related: bool = False
    similarities: list[str] = Field(default_factory=list)
    important_changes: list[str] = Field(default_factory=list)
    should_reuse_previous_conclusion: bool = False


class InquiryPossibleCondition(BaseModel):
    name: str = Field(min_length=1, max_length=36)
    likelihood: Literal["more_likely", "possible", "needs_exclusion"] = "possible"
    supporting_evidence: list[str] = Field(default_factory=list, max_length=2)
    non_supporting_evidence: list[str] = Field(default_factory=list, max_length=2)


class InquiryClinicalAssessment(BaseModel):
    summary: str = Field(default="", max_length=180)
    possible_conditions: list[InquiryPossibleCondition] = Field(default_factory=list, max_length=3)
    next_steps: list[str] = Field(default_factory=list, max_length=3)
    seek_care_if: list[str] = Field(default_factory=list, max_length=3)


class InquiryExtractedInformation(BaseModel):
    case_summary: str = ""
    observations: list[InquiryObservation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    history_relationship: InquiryHistoryRelationship = Field(default_factory=InquiryHistoryRelationship)
    ai_risk_level: RiskLevel | None = None
    ai_risk_reasons: list[str] = Field(default_factory=list)
    ai_available: bool = True
    symptom_dimensions: list[str] = Field(default_factory=list)
    dimension_evidence: dict[str, str] = Field(default_factory=dict)
    symptom_features: list[str] = Field(default_factory=list)
    feature_evidence: dict[str, str] = Field(default_factory=dict)
    clarification_answers: dict[str, str] = Field(default_factory=dict)
    asked_clarifications: list[str] = Field(default_factory=list)
    pending_clarification: str = ""
    symptom_scope_confirmed: bool = False
    symptom_revision: int = Field(default=0, ge=0)
    symptom_collection_complete: bool = False
    symptoms_text: str = ""
    duration: str = ""
    used_medicines: str = ""
    allergy_or_contraindication: str = ""
    confidence: float = 0.0
    final_assessment: InquiryClinicalAssessment = Field(default_factory=InquiryClinicalAssessment)


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
    reasoning_summary: str = ""
    model_action_intent: InquiryModelAction = "ask"
    action_reason: str = ""
    extracted_information: InquiryExtractedInformation = Field(default_factory=InquiryExtractedInformation)
    vitals: dict[str, Any] | None = None
    risk_level: RiskLevel | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    medication_safety_notices: list[MedicineSafetyNotice] = Field(default_factory=list)
    next_action: InquiryNextAction
    primary_candidate: CandidateMedicine | None = None
    alternative_candidate: CandidateMedicine | None = None
    treatment_options: list[TreatmentOption] = Field(default_factory=list)
    can_view_medicines: bool = False
    selected_option_id: str = ""
    action_status: InquiryActionStatus = "idle"
    action_message: str = ""
    action_progress_index: int = 0
    action_total_items: int = 0
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[InquiryMessage] = Field(default_factory=list)
    title: str = "新问询"
    created_at: str
    updated_at: str


class InquiryTreatmentConfirmRequest(BaseModel):
    option_id: str = Field(min_length=1, max_length=12)
    confirmed_safety_notice: bool
    expected_item_index: int = Field(default=0, ge=0, le=8)


class InquiryTreatmentDispenseItem(BaseModel):
    medicine_id: str
    medicine_name: str
    slot: str
    ok: bool
    dry_run: bool
    message: str
    record_id: str | None = None


class InquiryTreatmentConfirmResponse(BaseModel):
    ok: bool
    status: InquiryActionStatus
    option_id: str
    message: str
    items: list[InquiryTreatmentDispenseItem] = Field(default_factory=list)
    completed_count: int = 0
    total_count: int = 0
    next_medicine: TreatmentMedicine | None = None
    session: InquirySessionResponse
