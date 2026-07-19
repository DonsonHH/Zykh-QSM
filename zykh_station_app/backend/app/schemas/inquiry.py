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
    indications: str = ""
    dosage: str = ""
    match_reason: str = ""
    requires_existing_direction: bool = False


class TreatmentMedicine(CandidateMedicine):
    role: str = "主要对症"
    covered_symptoms: list[str] = Field(default_factory=list)


class TreatmentOption(BaseModel):
    option_id: str
    label: str
    when: str
    medicines: list[TreatmentMedicine] = Field(default_factory=list)


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


class InquiryMeasurementRequest(BaseModel):
    reason: str = Field(default="", max_length=240)
    goal: str = Field(default="", max_length=240)
    required_core_metrics: list[str] = Field(default_factory=list)


class InquiryVitalsMetric(BaseModel):
    value: float | str
    unit: str
    usable: bool
    quality: str


class InquiryVitalsEvidence(BaseModel):
    measurement_session_id: str = ""
    measurement_status: Literal["complete", "partial", "failed", "cancelled"] = "complete"
    core: dict[str, InquiryVitalsMetric] = Field(default_factory=dict)
    reference: dict[str, InquiryVitalsMetric] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    reliability_notes: list[str] = Field(default_factory=list)
    error_message: str = ""
    measured_at: str = ""


class InquiryVitalsRequest(BaseModel):
    measurement_session_id: str = ""
    status: Literal["complete", "partial", "failed", "cancelled"] = "complete"
    temperature: float | None = Field(default=None, gt=0, lt=50)
    heart_rate: int | None = Field(default=None, gt=0, lt=260)
    spo2: int | None = Field(default=None, gt=0, le=100)
    body_temperature: float | None = None
    systolic_pressure: int | None = None
    diastolic_pressure: int | None = None
    respiratory_rate: int | None = None
    hrv_sdnn: int | None = None
    hrv_rmssd: int | None = None
    rr_interval: int | None = None
    microcirculation: int | None = None
    fatigue: int | None = None
    ambient_temperature: float | None = None
    quality: str = ""
    reference_ready: bool | None = None
    finger_detected: bool | None = None
    sample_count: int | None = Field(default=None, ge=0)
    valid_frame_count: int | None = Field(default=None, ge=0)
    contact_frame_count: int | None = Field(default=None, ge=0)
    heart_rate_frame_count: int | None = Field(default=None, ge=0)
    spo2_frame_count: int | None = Field(default=None, ge=0)
    stabilization_extended: bool | None = None
    partial: bool = False
    source: str = ""
    error_message: str = ""
    measured_at: str = ""


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


class InquiryVitalsAssessment(BaseModel):
    core_findings: list[str] = Field(default_factory=list)
    reference_findings: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    answered_uncertainties: list[str] = Field(default_factory=list)


class InquiryCaseDocument(BaseModel):
    chief_complaint: str = ""
    course: str = ""
    positive_findings: list[str] = Field(default_factory=list)
    negative_findings: list[str] = Field(default_factory=list)
    remaining_uncertainties: list[str] = Field(default_factory=list)
    used_medicines: str = ""
    allergy_or_contraindication: str = ""
    core_vitals: list[str] = Field(default_factory=list)
    reference_vitals: list[str] = Field(default_factory=list)
    vitals_quality_notes: list[str] = Field(default_factory=list)
    integrated_summary: str = ""


class InquiryExtractedInformation(BaseModel):
    case_summary: str = ""
    observations: list[InquiryObservation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    history_relationship: InquiryHistoryRelationship = Field(default_factory=InquiryHistoryRelationship)
    ai_risk_level: RiskLevel | None = None
    ai_risk_reasons: list[str] = Field(default_factory=list)
    ai_available: bool = True
    measurement_request: InquiryMeasurementRequest | None = None
    vitals_assessment: InquiryVitalsAssessment | None = None
    case_document: InquiryCaseDocument | None = None
    vitals_measurement_attempts: int = Field(default=0, ge=0)
    vitals_measurement_status: str = "not_requested"
    symptom_dimensions: list[str] = Field(default_factory=list)
    dimension_evidence: dict[str, str] = Field(default_factory=dict)
    symptom_features: list[str] = Field(default_factory=list)
    feature_evidence: dict[str, str] = Field(default_factory=dict)
    clarification_answers: dict[str, str] = Field(default_factory=dict)
    asked_clarifications: list[str] = Field(default_factory=list)
    pending_clarification: str = ""
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
    reasoning_summary: str = ""
    model_action_intent: InquiryModelAction = "ask"
    action_reason: str = ""
    extracted_information: InquiryExtractedInformation = Field(default_factory=InquiryExtractedInformation)
    vitals: dict[str, Any] | None = None
    risk_level: RiskLevel | None = None
    risk_reasons: list[str] = Field(default_factory=list)
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
