from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.inquiry import InquiryEvaluateRequest, InquiryRecordResponse, InquiryRecordsResponse, InquiryResult
from ..services.inquiry_service import InquiryService

router = APIRouter(prefix="/api/inquiry", tags=["inquiry"])


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
