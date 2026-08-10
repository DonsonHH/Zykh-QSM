from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CheckStatus = Literal["PASSED", "BLOCKED", "CHECK_FAILED"]
DispenseStatus = Literal[
    "NOT_STARTED",
    "DISPENSED",
    "HARDWARE_FAILED",
    "RESULT_UNKNOWN",
]


class IdentityAssertion(BaseModel):
    assertion_id: str
    service_user_id: str
    verification_method: str
    verification_score: float | None = None
    created_at: str
    expires_at: str


class AssessManualMedicationCommand(BaseModel):
    request_id: str = Field(min_length=1, max_length=160)
    medicine_id: str = Field(min_length=1, max_length=160)
    slot: str = Field(min_length=1, max_length=32)
    service_user_id: str = Field(min_length=1, max_length=160)
    verification_method: Literal["face", "fingerprint"]
    verification_assertion_id: str = Field(min_length=1, max_length=160)
    expected_review_fingerprint: str = Field(min_length=1, max_length=128)


class ManualMedicationAssessment(BaseModel):
    ok: bool = True
    check_id: str
    check_status: CheckStatus
    reason_codes: list[str] = Field(default_factory=list)
    message: str
    expires_at: str = ""
    dispense_status: DispenseStatus = "NOT_STARTED"


class ConfirmManualMedicationCommand(BaseModel):
    request_id: str = Field(min_length=1, max_length=160)
    safety_check_id: str = Field(min_length=1, max_length=160)
    confirmed_safety_notice: bool


class ManualMedicationOutcome(BaseModel):
    ok: bool
    safety_check_id: str
    dispense_status: DispenseStatus
    message: str
    dispense_record_id: str = ""
    inventory_confirmation_required: bool = False


class ManualDispenseExecutionCommand(BaseModel):
    qsm_operation_id: str
    medicine_id: str
    medicine_name: str
    slot: str
    quantity: int = Field(default=1, ge=1)
    service_user_id: str
    service_user_name: str
    verification_method: str
    verification_assertion_id: str
    expected_persona_generation: str
    expected_safety_profile_revision: int
    expected_person_safety_fingerprint: str
    expected_review_fingerprint: str
    expected_hardware_slot: int
    expected_stock: int
    expected_expire_date: str


class ManualDispenseExecutionResult(BaseModel):
    dispense_status: Literal["DISPENSED", "HARDWARE_FAILED", "RESULT_UNKNOWN"]
    message: str
    dispense_record_id: str = ""
    inventory_confirmation_required: bool = False
