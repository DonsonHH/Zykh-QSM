from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..repositories.manual_medication_access_repository import (
    ManualAccessIdempotencyConflict,
)
from ..schemas.manual_medication_access import (
    AssessManualMedicationCommand,
    ConfirmManualMedicationCommand,
    ManualMedicationAssessment,
    ManualMedicationOutcome,
)
from ..services.manual_medication_access_module import ManualMedicationAccessModule


router = APIRouter(
    prefix="/api/manual-medication-access",
    tags=["manual-medication-access"],
)


def get_manual_medication_access_module() -> ManualMedicationAccessModule:
    return ManualMedicationAccessModule()


ManualAccessDependency = Annotated[
    ManualMedicationAccessModule,
    Depends(get_manual_medication_access_module),
]


@router.post("/assess", response_model=ManualMedicationAssessment)
def assess_manual_medication(
    request: AssessManualMedicationCommand,
    module: ManualAccessDependency,
) -> ManualMedicationAssessment:
    try:
        return module.assess(request)
    except ManualAccessIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/confirm", response_model=ManualMedicationOutcome)
def confirm_manual_medication(
    request: ConfirmManualMedicationCommand,
    module: ManualAccessDependency,
) -> ManualMedicationOutcome:
    try:
        return module.confirm(request)
    except ManualAccessIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
