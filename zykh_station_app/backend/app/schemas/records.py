from __future__ import annotations

from pydantic import BaseModel


class RecordsSummary(BaseModel):
    today_service_users: int
    pending_sync_count: int
    local_record_count: int
    today_plan_count: int


class RecentRecord(BaseModel):
    id: str
    time: str
    type: str
    title: str
    description: str
    target_user: str
    status: str
    sync_status: str


class RecordsSummaryResponse(BaseModel):
    ok: bool = True
    summary: RecordsSummary


class RecentRecordsResponse(BaseModel):
    ok: bool = True
    records: list[RecentRecord]
