from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.dispense import DispenseConfirmRequest, DispenseConfirmResponse, DispenseRecordsResponse
from ..services.dispense_service import DispenseError, DispenseService

router = APIRouter(prefix="/api/dispense", tags=["dispense"])


@router.post("/confirm", response_model=DispenseConfirmResponse)
def confirm_dispense(request: DispenseConfirmRequest) -> DispenseConfirmResponse:
    try:
        return DispenseService().confirm(request)
    except DispenseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/records", response_model=DispenseRecordsResponse)
def dispense_records() -> DispenseRecordsResponse:
    return DispenseRecordsResponse(records=DispenseService().list_records())
