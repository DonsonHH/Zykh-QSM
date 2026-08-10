from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..schemas.records import RecordsSummaryResponse, RecentRecordsResponse, ServiceUserCreateRequest, ServiceUserInquiryHistoryResponse, ServiceUserUpdateRequest, ServiceUsersResponse, TodayPlansResponse
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


@router.get(
    "/service-users/{user_id}/inquiries",
    response_model=ServiceUserInquiryHistoryResponse,
)
def service_user_inquiries(
    user_id: str,
    limit: int = Query(default=20, ge=1, le=20),
    cursor: str | None = Query(default=None, max_length=120),
) -> ServiceUserInquiryHistoryResponse:
    try:
        return RecordsService().list_service_user_inquiries(
            user_id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "服务对象不存在" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/today-plans", response_model=TodayPlansResponse)
def today_plans() -> TodayPlansResponse:
    return TodayPlansResponse(plans=RecordsService().list_today_plans(due_only=True))
