from __future__ import annotations

from fastapi import APIRouter

from ..schemas.sync import SyncMockResponse, SyncStatus
from ..services.sync_service import SyncService

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatus)
def sync_status() -> SyncStatus:
    return SyncService().get_status()


@router.post("/mock", response_model=SyncMockResponse)
def mock_sync() -> SyncMockResponse:
    return SyncService().mock_sync()


@router.post("/run", response_model=SyncMockResponse)
def run_sync() -> SyncMockResponse:
    return SyncService().mock_sync()
