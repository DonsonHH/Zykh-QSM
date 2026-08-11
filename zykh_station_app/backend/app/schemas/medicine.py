from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION = "case-applicability-v1"


class Medicine(BaseModel):
    id: str
    slot: str
    hardware_slot: int = 0
    barcode: str = ""
    manufacturer: str = ""
    name: str
    category: str
    spec: str = ""
    trace_code: str = ""
    tags: list[str]
    aliases: list[str] = Field(default_factory=list)
    active_ingredients: list[str] = Field(default_factory=list)
    indications: str = ""
    dosage: str = ""
    contraindications: list[str]
    structured_contraindications: list[dict[str, str]] = Field(default_factory=list)
    stock: int
    low_stock_line: int = 1
    unit: str
    expire_date: str
    image_hint: str
    is_otc: bool
    is_emergency: bool
    safety_note: str
    guidance_source: str = "pending"
    guidance_review_required: bool = True
    package_verified: bool = True
    guidance_updated_at: str = ""
    safety_review_status: str = "draft"
    safety_reviewed_by: str = ""
    safety_reviewed_at: str = ""
    review_fingerprint: str = ""
    dispense_count: int = 0
    inventory_state: Literal["AVAILABLE", "DEPLETED", "UNKNOWN"] = "UNKNOWN"
    inventory_revision: int = 0
    inventory_confirmed_at: str = ""
    last_inventory_request_id: str = ""
    last_inventory_dispense_record_id: str = ""


class MedicineListResponse(BaseModel):
    ok: bool = True
    total: int
    warehouse_total: int = 23
    categories: list[str]
    medicines: list[Medicine]


class MedicineDetailResponse(BaseModel):
    ok: bool = True
    medicine: Medicine


class MedicineUpdateRequest(BaseModel):
    name: str | None = None
    manufacturer: str | None = None
    barcode: str | None = None
    category: str | None = None
    spec: str | None = None
    trace_code: str | None = None
    tags: list[str] | None = None
    aliases: list[str] | None = None
    active_ingredients: list[str] | None = None
    indications: str | None = None
    dosage: str | None = None
    contraindications: list[str] | None = None
    structured_contraindications: list[dict[str, str]] | None = None
    stock: int | None = None
    low_stock_line: int | None = None
    unit: str | None = None
    expire_date: str | None = None
    safety_note: str | None = None
    is_otc: bool | None = None
    is_emergency: bool | None = None


class MedicineUpdateResponse(BaseModel):
    ok: bool = True
    message: str
    medicine: Medicine


class MedicineInventoryConfirmationRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    dispense_record_id: str = Field(min_length=1, max_length=128)
    observation: Literal["HAS_REMAINING", "DEPLETED"]


class MedicineInventoryConfirmationResponse(BaseModel):
    ok: bool = True
    replayed: bool = False
    medicine_id: str
    dispense_record_id: str
    observation: Literal["HAS_REMAINING", "DEPLETED"]
    stock: int
    inventory_state: Literal["AVAILABLE", "DEPLETED", "UNKNOWN"]
    inventory_confirmed_at: str
    message: str


class MedicineCombinationApplicability(BaseModel):
    required_all_facts: list[str] = Field(default_factory=list)
    required_any_facts: list[str] = Field(default_factory=list)
    must_be_absent_facts: list[str] = Field(default_factory=list)
    member_required_any_facts: dict[str, list[str]] = Field(default_factory=dict)
    allowed_risk_levels: list[str] = Field(default_factory=list)
    min_age_years: int | None = Field(default=None, ge=0, le=130)
    max_age_years: int | None = Field(default=None, ge=0, le=130)


class MedicineCombinationEvidenceRef(BaseModel):
    source_title: str = ""
    source_url: str = ""
    supports: str = ""


class ApprovedMedicineCombination(BaseModel):
    combination_id: str
    label: str
    medicine_ids: list[str] = Field(default_factory=list)
    member_identity_fingerprints: dict[str, str] = Field(default_factory=dict)
    clinical_policy_version: str = ""
    applicability: MedicineCombinationApplicability = Field(
        default_factory=MedicineCombinationApplicability
    )
    member_review_fingerprints: dict[str, str] = Field(default_factory=dict)
    reviewed_usage_by_medicine: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[MedicineCombinationEvidenceRef] = Field(default_factory=list)
    provenance: str = ""
    review_note: str = ""
    review_status: str = "draft"
    reviewed_by: str = ""
    reviewed_at: str = ""
    updated_at: str = ""


class MedicineIngredientConflictRule(BaseModel):
    left_ingredient: str
    right_ingredient: str
    disposition: str = "block"
    message: str = ""
    review_status: str = "draft"
    reviewed_by: str = ""
    reviewed_at: str = ""
    updated_at: str = ""


class MedicineScanRequest(BaseModel):
    mode: str = "药品识别"
    manual_code: str | None = None


class MedicineScanFrameRequest(BaseModel):
    mode: str = "药品识别"
    image_data: str


class MedicineScanResult(BaseModel):
    ok: bool
    status: str
    image_path: str | None = None
    image_url: str | None = None
    barcode: str | None = None
    medicine_id: str | None = None
    name: str | None = None
    match_percent: int | None = None
    spec: str | None = None
    quantity: str | None = None
    expire_date: str | None = None
    slot: str | None = None
    source: str = "local"
    error_message: str | None = None


class MedicineScanRegisterRequest(BaseModel):
    barcode: str | None = None
    manufacturer: str | None = None
    name: str | None = None
    spec: str | None = None
    expire_date: str | None = None
    slot: int | None = None
    stock: int = 1
    unit: str = "盒"
    category: str = "扫码录入"
    indications: str | None = None
    dosage: str | None = None
    safety_note: str | None = None


class MedicineScanRegisterResponse(BaseModel):
    ok: bool
    created: bool
    message: str
    medicine: Medicine | None = None


class MedicineVisualRecognizeRequest(BaseModel):
    image_path: str | None = None


class MedicineVisualRecognizeResponse(BaseModel):
    ok: bool
    source: str
    raw_text: str | None = None
    barcode: str | None = None
    name: str | None = None
    expire_date: str | None = None
    error_message: str | None = None
