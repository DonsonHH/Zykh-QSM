from __future__ import annotations

import threading
from uuid import uuid4

from .. import db
from ..config import settings
from ..db import now_text
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.medicine_repository import MedicineRepository
from ..schemas.dispense import (
    DispenseConfirmRequest,
    DispenseConfirmResponse,
    DispenseOpenRequest,
    DispenseOpenResponse,
    DispenseRecord,
)
from .qsm_client import QsmClient
from .dispense_archive_service import DispenseArchiveService
from .medicine_knowledge_repository import MedicineKnowledgeRepository


class DispenseError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DispenseService:
    _plan_dispense_lock = threading.Lock()

    def __init__(
        self,
        medicine_repository: MedicineRepository | None = None,
        dispense_repository: DispenseRepository | None = None,
        qsm_client: QsmClient | None = None,
        archive_service: DispenseArchiveService | None = None,
    ) -> None:
        self.medicine_repository = medicine_repository or MedicineRepository()
        self.dispense_repository = dispense_repository or DispenseRepository()
        self.qsm_client = qsm_client or QsmClient()
        self.archive_service = archive_service or DispenseArchiveService()

    def confirm(self, request: DispenseConfirmRequest, force_dry_run: bool | None = None) -> DispenseConfirmResponse:
        if request.today_plan_id:
            with self._plan_dispense_lock:
                return self._confirm(request, force_dry_run)
        return self._confirm(request, force_dry_run)

    def _confirm(self, request: DispenseConfirmRequest, force_dry_run: bool | None = None) -> DispenseConfirmResponse:
        medicine = self.medicine_repository.get_by_id(request.medicine_id)
        if medicine is None:
            raise DispenseError("未找到该药品。", status_code=404)
        if request.slot != medicine.slot:
            raise DispenseError("药品仓位与当前库存记录不一致。")
        if request.confirmed_safety_notice is not True:
            raise DispenseError("请先阅读并确认药品说明与安全提示。")
        if medicine.guidance_source == "pending":
            raise DispenseError("该药品资料尚未补全，完成实物包装和说明书核验前不可取药。")
        if not medicine.package_verified:
            raise DispenseError("该药品包装规格尚未人工核验，核验完成前不可取药。")
        if request.verification_method == "inquiry_confirmed" and (
            medicine.safety_review_status != "reviewed"
            or not medicine.safety_reviewed_by.strip()
            or not medicine.safety_reviewed_at.strip()
        ):
            raise DispenseError("该药品安全资料尚未完成审核，审核完成前不可取药。")
        if MedicineKnowledgeRepository.is_expired(medicine.expire_date):
            raise DispenseError("该药品已过有效期，不可取药；请联系管理员更换库存。")
        if medicine.stock < request.quantity:
            raise DispenseError("当前库存不足，不能执行取药。", status_code=409)
        if not medicine.is_otc and not request.today_plan_id:
            raise DispenseError("该药品需凭处方或既往用药计划取用，请先完成医生审核。")
        canonical_name, target_user_type = self._resolve_identity(request.target_user_id, request.target_user_name)
        registered_allergies = self._registered_allergies(request.target_user_id)
        if registered_allergies and MedicineKnowledgeRepository.has_allergy_conflict(
            medicine,
            registered_allergies,
        ):
            raise DispenseError(
                f"已登记的用药禁忌（{registered_allergies}）与{medicine.name}冲突，不可取药。"
            )
        request = request.model_copy(update={"target_user_name": canonical_name})
        if request.today_plan_id:
            from .records_service import RecordsService

            try:
                RecordsService().validate_dispense_plan(
                    request.today_plan_id,
                    request.medicine_id,
                    request.target_user_id,
                )
            except ValueError as exc:
                raise DispenseError(str(exc)) from exc
        latest = self.medicine_repository.get_by_id(request.medicine_id)
        if latest is None or latest.slot != request.slot:
            raise DispenseError("药品库存记录已经变化，请重新核对。", status_code=409)
        if latest.stock < request.quantity:
            raise DispenseError("当前库存不足，不能执行取药。", status_code=409)
        if request.expected_review_fingerprint:
            if (
                MedicineKnowledgeRepository.review_fingerprint(latest)
                != request.expected_review_fingerprint
            ):
                raise DispenseError(
                    "药品身份或安全资料已变化，请重新核对后再取药。",
                    status_code=409,
                )
        medicine = latest
        dry_run = self._should_dry_run(request, medicine, force_dry_run)
        qsm_result = self.qsm_client.dispense(str(medicine.hardware_slot or medicine.slot), request.quantity, dry_run=dry_run)
        qsm_ok = bool(qsm_result.get("ok"))
        qsm_detail = str(qsm_result.get("detail") or qsm_result.get("error_message") or "")
        if not dry_run and not qsm_ok:
            message = f"外设开柜失败：{qsm_detail or '未返回成功状态'}"
            record = self._build_record(
                request,
                medicine,
                dry_run,
                message,
                qsm_ok=False,
                qsm_detail=qsm_detail,
                target_user_type=target_user_type,
            )
            self.dispense_repository.append(record)
            self._archive_identity_if_requested(request, record, target_user_type)
            return DispenseConfirmResponse(ok=False, dry_run=False, message=message, record_id=record.id, qsm_detail=qsm_detail)

        message = "本地测试记录已保存，未打开柜门。" if dry_run else "取药确认已完成，柜门已打开。"
        record = self._build_record(
            request,
            medicine,
            dry_run,
            message,
            qsm_ok=qsm_ok,
            qsm_detail=qsm_detail,
            target_user_type=target_user_type,
        )
        self.dispense_repository.append(record)
        self._archive_identity_if_requested(request, record, target_user_type)
        if request.today_plan_id and not dry_run:
            from .records_service import RecordsService

            RecordsService().complete_today_plan(
                request.today_plan_id,
                request.medicine_id,
                request.target_user_id,
            )
        return DispenseConfirmResponse(ok=True, dry_run=dry_run, message=message, record_id=record.id, qsm_detail=qsm_detail)

    def _archive_identity_if_requested(
        self,
        request: DispenseConfirmRequest,
        record: DispenseRecord,
        target_user_type: str,
    ) -> None:
        if not request.archive_identity_snapshot or target_user_type != "guest" or record.dry_run:
            return
        try:
            self.archive_service.capture_for_record(record)
        except Exception:
            # Photo retention is supplemental evidence and must never block a confirmed cabinet action.
            return

    def open_cabinet(self, request: DispenseOpenRequest) -> DispenseOpenResponse:
        if request.confirmed_open is not True:
            raise DispenseError("请先确认现场安全，避免误开柜门。")

        allowed_slot = settings.real_dispense_test_slot.strip()
        dry_run = settings.dispense_dry_run or not settings.enable_real_dispense
        if not dry_run and allowed_slot and allowed_slot != str(request.slot):
            raise DispenseError("真实开柜测试仓位与请求仓位不一致，已拒绝执行。")

        qsm_result = self.qsm_client.dispense(str(request.slot), request.quantity, dry_run=dry_run)
        qsm_ok = bool(qsm_result.get("ok"))
        qsm_detail = str(qsm_result.get("detail") or qsm_result.get("error_message") or "")
        if dry_run:
            return DispenseOpenResponse(
                ok=True,
                dry_run=True,
                slot=request.slot,
                message="本地测试记录已保存，未打开柜门。",
                qsm_detail=qsm_detail,
            )
        if not qsm_ok:
            return DispenseOpenResponse(
                ok=False,
                dry_run=False,
                slot=request.slot,
                message=f"外设开柜失败：{qsm_detail or '未返回成功状态'}",
                qsm_detail=qsm_detail,
            )
        if request.target_user_name and request.medicine_id:
            medicine = self.medicine_repository.get_by_id(request.medicine_id)
            if medicine is not None:
                target_user_name, target_user_type = self._resolve_identity(
                    request.target_user_id,
                    request.target_user_name,
                    require_known=False,
                )
                record = DispenseRecord(
                    id=f"dispense-{uuid4().hex[:12]}",
                    medicine_id=medicine.id,
                    medicine_name=medicine.name,
                    slot=medicine.slot,
                    hardware_slot=medicine.hardware_slot,
                    quantity=request.quantity,
                    unit=medicine.unit,
                    reason=request.reason,
                    dry_run=False,
                    message=f"{target_user_name}已打开{medicine.hardware_slot}号柜。",
                    qsm_ok=True,
                    qsm_detail=qsm_detail,
                    target_user_id=request.target_user_id,
                    target_user_name=target_user_name,
                    verification_method="manual",
                    verification_score=None,
                    target_user_type=target_user_type,
                    created_at=now_text(),
                )
                self.dispense_repository.append(record)
        return DispenseOpenResponse(
            ok=True,
            dry_run=False,
            slot=request.slot,
            message=f"{request.slot}号柜门已打开。",
            qsm_detail=qsm_detail,
        )

    def list_records(self) -> list[DispenseRecord]:
        return self.dispense_repository.list_records()

    @staticmethod
    def _should_dry_run(
        request: DispenseConfirmRequest,
        medicine,
        force_dry_run: bool | None,
    ) -> bool:
        if force_dry_run is not None:
            return force_dry_run
        if settings.dispense_dry_run:
            return True
        if not settings.enable_real_dispense:
            return True
        if request.confirm_real_dispense is not True:
            return True
        allowed_slot = settings.real_dispense_test_slot.strip()
        if not allowed_slot:
            return False
        hardware_slot = str(medicine.hardware_slot or "")
        if allowed_slot not in {hardware_slot, medicine.slot}:
            raise DispenseError("真实取药测试仓位与当前药品仓位不一致，已拒绝执行。")
        return False

    @staticmethod
    def _build_record(
        request: DispenseConfirmRequest,
        medicine,
        dry_run: bool,
        message: str,
        qsm_ok: bool,
        qsm_detail: str,
        target_user_type: str,
    ) -> DispenseRecord:
        record_id = f"{'dryrun' if dry_run else 'dispense'}-{uuid4().hex[:12]}"
        return DispenseRecord(
            id=record_id,
            medicine_id=medicine.id,
            medicine_name=medicine.name,
            slot=medicine.slot,
            hardware_slot=medicine.hardware_slot,
            quantity=request.quantity,
            unit=medicine.unit,
            reason=request.reason,
            dry_run=dry_run,
            message=message,
            qsm_ok=qsm_ok,
            qsm_detail=qsm_detail,
            target_user_id=request.target_user_id,
            target_user_name=request.target_user_name.strip() or "家庭成员",
            verification_method=request.verification_method.strip() or "manual",
            verification_score=request.verification_score,
            target_user_type=target_user_type,
            today_plan_id=request.today_plan_id,
            created_at=now_text(),
        )

    @staticmethod
    def _resolve_identity(
        target_user_id: str,
        target_user_name: str,
        *,
        require_known: bool = True,
    ) -> tuple[str, str]:
        user_id = str(target_user_id or "").strip()
        supplied_name = str(target_user_name or "").strip()
        if user_id:
            db.init_db()
            with db.connect() as conn:
                row = conn.execute(
                    "SELECT name, status FROM service_users WHERE id=?",
                    (user_id,),
                ).fetchone()
            if row:
                status = str(row["status"] or "")
                user_type = "guest" if user_id.startswith("guest-") or status in {"访客", "游客"} else "registered"
                return str(row["name"]), user_type
            if require_known:
                raise DispenseError("身份记录不存在，请重新进行指纹或面部确认。")
        if supplied_name:
            visitor = supplied_name.startswith(("访客", "游客"))
            return supplied_name, "guest" if visitor or not user_id else "registered"
        return "游客", "guest"

    @staticmethod
    def _registered_allergies(target_user_id: str) -> str:
        user_id = str(target_user_id or "").strip()
        if not user_id:
            return ""
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT allergies FROM service_users WHERE id=?",
                (user_id,),
            ).fetchone()
        return str(row["allergies"] or "").strip() if row else ""
