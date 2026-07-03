from __future__ import annotations

from fastapi import APIRouter

from ..schemas.records import RecordsSummaryResponse, RecentRecordsResponse
from ..services.records_service import RecordsService

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("/summary", response_model=RecordsSummaryResponse)
def records_summary() -> RecordsSummaryResponse:
    return RecordsSummaryResponse(summary=RecordsService().get_summary())


@router.get("/recent", response_model=RecentRecordsResponse)
def recent_records() -> RecentRecordsResponse:
    return RecentRecordsResponse(records=RecordsService().get_recent_records())

