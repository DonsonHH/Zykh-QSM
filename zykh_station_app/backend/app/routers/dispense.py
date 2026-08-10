from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.dispense import (
    DispenseConfirmRequest,
    DispenseConfirmResponse,
    DispenseOpenRequest,
    DispenseOpenResponse,
    DispenseRecordsResponse,
)
from ..services.dispense_service import DispenseError, DispenseService
from ..services.dispense_route import classify_dispense_route

router = APIRouter(prefix="/api/dispense", tags=["dispense"])


@router.post("", response_model=DispenseOpenResponse)
def open_cabinet(request: DispenseOpenRequest) -> DispenseOpenResponse:
    del request
    raise HTTPException(
        status_code=403,
        detail="直接开柜接口已停用；请使用现场安全取药确认或管理员调试台。",
    )


@router.post("/confirm", response_model=DispenseConfirmResponse)
def confirm_dispense(request: DispenseConfirmRequest) -> DispenseConfirmResponse:
    if classify_dispense_route(request) == "INQUIRY":
        raise HTTPException(
            status_code=409,
            detail="问询方案必须通过原问询会话的确认接口取药。",
        )
    try:
        return DispenseService().confirm(request)
    except DispenseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/records", response_model=DispenseRecordsResponse)
def dispense_records() -> DispenseRecordsResponse:
    return DispenseRecordsResponse(records=DispenseService().list_records())
