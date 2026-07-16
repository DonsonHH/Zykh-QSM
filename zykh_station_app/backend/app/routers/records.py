from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas.records import RecordsSummaryResponse, RecentRecordsResponse, ServiceUserCreateRequest, ServiceUserUpdateRequest, ServiceUsersResponse, TodayPlansResponse
from ..services.records_service import RecordsService

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("/summary", response_model=RecordsSummaryResponse)
def records_summary() -> RecordsSummaryResponse:
    return RecordsSummaryResponse(summary=RecordsService().get_summary())


@router.get("/recent", response_model=RecentRecordsResponse)
def recent_records() -> RecentRecordsResponse:
    return RecentRecordsResponse(records=RecordsService().get_recent_records())


@router.get("/service-users", response_model=ServiceUsersResponse)
def service_users() -> ServiceUsersResponse:
    return ServiceUsersResponse(users=RecordsService().list_service_users())


@router.post("/service-users", response_model=ServiceUsersResponse)
def create_service_user(request: ServiceUserCreateRequest) -> ServiceUsersResponse:
    service = RecordsService()
    service.create_service_user(request)
    return ServiceUsersResponse(users=service.list_service_users())


@router.patch("/service-users/{user_id}", response_model=ServiceUsersResponse)
def update_service_user(user_id: str, request: ServiceUserUpdateRequest) -> ServiceUsersResponse:
    service = RecordsService()
    try:
        service.update_service_user(user_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ServiceUsersResponse(users=service.list_service_users())


@router.delete("/service-users/{user_id}", response_model=ServiceUsersResponse)
def delete_service_user(user_id: str) -> ServiceUsersResponse:
    service = RecordsService()
    try:
        service.delete_service_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ServiceUsersResponse(users=service.list_service_users())


@router.get("/today-plans", response_model=TodayPlansResponse)
def today_plans() -> TodayPlansResponse:
    return TodayPlansResponse(plans=RecordsService().list_today_plans(due_only=True))
