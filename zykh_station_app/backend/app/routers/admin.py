from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from ..schemas.admin import (
    AdminActionResponse,
    AdminBiometricResponse,
    AdminCabinetOpenRequest,
    AdminConfirmationRequest,
    AdminLogsResponse,
    AdminMedicinesResponse,
    AdminMedicineUpdateRequest,
    AdminOverviewResponse,
    AdminSessionRequest,
    AdminSessionResponse,
    AdminSystemActionRequest,
    AdminTodayPlanCreateRequest,
    AdminTodayPlansResponse,
    AdminTodayPlanUpdateRequest,
    AdminUserCreateRequest,
    AdminUsersResponse,
    AdminUserUpdateRequest,
)
from ..schemas.dispense import DispenseOpenResponse
from ..services.admin_auth_service import AdminAuthError, AdminAuthService
from ..services.admin_service import AdminService, AdminServiceError


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="需要管理员会话。")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="需要管理员会话。")
    return token


def require_admin(authorization: str | None = Header(default=None)) -> str:
    token = _bearer_token(authorization)
    try:
        AdminAuthService().verify(token)
    except AdminAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return token


def _service_error(exc: AdminServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/session", response_model=AdminSessionResponse)
def create_session(payload: AdminSessionRequest, request: Request) -> AdminSessionResponse:
    try:
        session = AdminAuthService().create_session(payload.pin, request.client.host if request.client else "unknown")
    except AdminAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    expires_in = max(0, int((session.expires_at - datetime.now().astimezone()).total_seconds()))
    return AdminSessionResponse(
        token=session.token,
        expires_at=session.expires_at.isoformat(timespec="seconds"),
        expires_in_seconds=expires_in,
    )


@router.delete("/session")
def delete_session(token: str = Depends(require_admin)) -> dict[str, object]:
    AdminAuthService().revoke(token)
    return {"ok": True}


@router.get("/overview", response_model=AdminOverviewResponse)
def admin_overview(_: str = Depends(require_admin)) -> AdminOverviewResponse:
    return AdminOverviewResponse(**AdminService().overview())


@router.get("/logs", response_model=AdminLogsResponse)
def admin_logs(source: str = "backend", limit: int = Query(default=300, ge=20, le=1000), _: str = Depends(require_admin)) -> AdminLogsResponse:
    return AdminLogsResponse(**AdminService().logs(source, limit))


@router.post("/system/action", response_model=AdminActionResponse)
def admin_system_action(payload: AdminSystemActionRequest, _: str = Depends(require_admin)) -> AdminActionResponse:
    try:
        return AdminActionResponse(**AdminService().system_action(payload.action, payload.confirmation))
    except AdminServiceError as exc:
        raise _service_error(exc) from exc


@router.get("/users", response_model=AdminUsersResponse)
def admin_users(_: str = Depends(require_admin)) -> AdminUsersResponse:
    users, biometrics = AdminService().list_users()
    return AdminUsersResponse(users=users, biometrics=biometrics)


@router.post("/users", response_model=AdminUsersResponse)
def admin_create_user(payload: AdminUserCreateRequest, _: str = Depends(require_admin)) -> AdminUsersResponse:
    service = AdminService()
    service.create_user(payload)
    users, biometrics = service.list_users()
    return AdminUsersResponse(users=users, biometrics=biometrics)


@router.patch("/users/{user_id}", response_model=AdminUsersResponse)
def admin_update_user(user_id: str, payload: AdminUserUpdateRequest, _: str = Depends(require_admin)) -> AdminUsersResponse:
    service = AdminService()
    try:
        service.update_user(user_id, payload)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    users, biometrics = service.list_users()
    return AdminUsersResponse(users=users, biometrics=biometrics)


@router.delete("/users/{user_id}", response_model=AdminUsersResponse)
def admin_delete_user(user_id: str, payload: AdminConfirmationRequest, _: str = Depends(require_admin)) -> AdminUsersResponse:
    service = AdminService()
    try:
        service.delete_user(user_id, payload.confirmation)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    users, biometrics = service.list_users()
    return AdminUsersResponse(users=users, biometrics=biometrics)


@router.post("/users/{user_id}/face", response_model=AdminBiometricResponse)
def admin_enroll_face(user_id: str, _: str = Depends(require_admin)) -> AdminBiometricResponse:
    result = AdminService().enroll_face(user_id)
    return AdminBiometricResponse(ok=result.ok, status=result.status, message=result.message, user=result.user)


@router.delete("/users/{user_id}/face", response_model=AdminBiometricResponse)
def admin_unbind_face(user_id: str, payload: AdminConfirmationRequest, _: str = Depends(require_admin)) -> AdminBiometricResponse:
    try:
        message = AdminService().unbind_face(user_id, payload.confirmation)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    return AdminBiometricResponse(ok=True, status="unbound", message=message)


@router.post("/users/{user_id}/fingerprint", response_model=AdminBiometricResponse)
def admin_enroll_fingerprint(user_id: str, _: str = Depends(require_admin)) -> AdminBiometricResponse:
    result = AdminService().enroll_fingerprint(user_id)
    return AdminBiometricResponse(ok=result.ok, status=result.status, message=result.message, user=result.user)


@router.delete("/users/{user_id}/fingerprint", response_model=AdminBiometricResponse)
def admin_delete_fingerprint(user_id: str, payload: AdminConfirmationRequest, _: str = Depends(require_admin)) -> AdminBiometricResponse:
    try:
        result = AdminService().delete_fingerprint(user_id, payload.confirmation)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    return AdminBiometricResponse(ok=result.ok, status=result.status, message=result.message, user=result.user)


@router.get("/medicines", response_model=AdminMedicinesResponse)
def admin_medicines(_: str = Depends(require_admin)) -> AdminMedicinesResponse:
    return AdminMedicinesResponse(medicines=AdminService().list_medicines())


@router.patch("/medicines/{medicine_id}", response_model=AdminMedicinesResponse)
def admin_update_medicine(medicine_id: str, payload: AdminMedicineUpdateRequest, _: str = Depends(require_admin)) -> AdminMedicinesResponse:
    service = AdminService()
    try:
        service.update_medicine(medicine_id, payload)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    return AdminMedicinesResponse(medicines=service.list_medicines())


def _today_plan_response(service: AdminService) -> AdminTodayPlansResponse:
    plans, users, medicines = service.list_today_plans()
    return AdminTodayPlansResponse(plans=plans, users=users, medicines=medicines)


@router.get("/today-plans", response_model=AdminTodayPlansResponse)
def admin_today_plans(_: str = Depends(require_admin)) -> AdminTodayPlansResponse:
    return _today_plan_response(AdminService())


@router.post("/today-plans", response_model=AdminTodayPlansResponse)
def admin_create_today_plan(payload: AdminTodayPlanCreateRequest, _: str = Depends(require_admin)) -> AdminTodayPlansResponse:
    service = AdminService()
    try:
        service.create_today_plan(payload)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    return _today_plan_response(service)


@router.patch("/today-plans/{plan_id}", response_model=AdminTodayPlansResponse)
def admin_update_today_plan(plan_id: str, payload: AdminTodayPlanUpdateRequest, _: str = Depends(require_admin)) -> AdminTodayPlansResponse:
    service = AdminService()
    try:
        service.update_today_plan(plan_id, payload)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    return _today_plan_response(service)


@router.delete("/today-plans/{plan_id}", response_model=AdminTodayPlansResponse)
def admin_delete_today_plan(plan_id: str, payload: AdminConfirmationRequest, _: str = Depends(require_admin)) -> AdminTodayPlansResponse:
    service = AdminService()
    try:
        service.delete_today_plan(plan_id, payload.confirmation)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
    return _today_plan_response(service)


@router.post("/cabinet/{slot}/open", response_model=DispenseOpenResponse)
def admin_open_cabinet(slot: int, payload: AdminCabinetOpenRequest, _: str = Depends(require_admin)) -> DispenseOpenResponse:
    try:
        return AdminService().open_cabinet(slot, payload.confirmation, payload.reason)
    except AdminServiceError as exc:
        raise _service_error(exc) from exc
