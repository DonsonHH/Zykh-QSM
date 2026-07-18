from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.inquiry import (
    InquiryEvaluateRequest,
    InquiryRecordResponse,
    InquiryRecordsResponse,
    InquiryResult,
    InquirySessionCreateRequest,
    InquirySessionResponse,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from ..services.inquiry_orchestrator import InquiryOrchestrator
from ..services.inquiry_service import InquiryService

router = APIRouter(prefix="/api/inquiry", tags=["inquiry"])


@router.post("/sessions", response_model=InquirySessionResponse)
def create_inquiry_session(request: InquirySessionCreateRequest) -> InquirySessionResponse:
    return InquiryOrchestrator().create_session(request)


@router.get("/sessions", response_model=list[InquirySessionResponse])
def list_inquiry_sessions() -> list[InquirySessionResponse]:
    return InquiryOrchestrator().repository.list_sessions()


@router.get("/sessions/{session_id}", response_model=InquirySessionResponse)
def get_inquiry_session(session_id: str) -> InquirySessionResponse:
    try:
        return InquiryOrchestrator().get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/turn", response_model=InquirySessionResponse)
def process_inquiry_turn(session_id: str, request: InquiryTurnRequest) -> InquirySessionResponse:
    try:
        return InquiryOrchestrator().process_turn(session_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/vitals", response_model=InquirySessionResponse)
def attach_inquiry_vitals(session_id: str, request: InquiryVitalsRequest) -> InquirySessionResponse:
    try:
        return InquiryOrchestrator().attach_vitals(session_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evaluate", response_model=InquiryResult)
def evaluate_inquiry(request: InquiryEvaluateRequest) -> InquiryResult:
    return InquiryService().evaluate(request)


@router.get("/records", response_model=InquiryRecordsResponse)
def inquiry_records() -> InquiryRecordsResponse:
    return InquiryRecordsResponse(records=InquiryService().list_records())


@router.get("/{inquiry_id}", response_model=InquiryRecordResponse)
def get_inquiry(inquiry_id: str) -> InquiryRecordResponse:
    result = InquiryService().get_result(inquiry_id)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到该问询结果。")
    return InquiryRecordResponse(result=result)
