from __future__ import annotations

from hashlib import sha256
import threading
from uuid import uuid4

from .. import db
from ..config import settings
from ..db import now_text
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.medicine_repository import MedicineRepository
from ..repositories.manual_medication_access_repository import (
    ManualExecutionPreconditionError,
    ManualMedicationAccessRepository,
)
from ..schemas.dispense import (
    DispenseConfirmRequest,
    DispenseConfirmResponse,
    DispenseOpenRequest,
    DispenseOpenResponse,
    DispenseRecord,
)
from ..schemas.manual_medication_access import ManualDispenseExecutionCommand
from .cabinet_v2_catalog import CabinetMappingError, cabinet_for_medicine_id
from .dispense_archive_service import DispenseArchiveService
from .dispense_route import classify_dispense_route
from .medicine_knowledge_repository import MedicineKnowledgeRepository
from .qsm_client import QsmClient


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
        if classify_dispense_route(request) == "MANUAL_INVENTORY":
            raise DispenseError(
                "普通库存取药必须先完成身份确认和个人用药安全核查。",
                status_code=409,
            )
        if request.today_plan_id:
            with self._plan_dispense_lock:
                return self._confirm(request, force_dry_run)
        return self._confirm(request, force_dry_run)

    def confirm_checked_manual(
        self,
        command: ManualDispenseExecutionCommand,
    ) -> DispenseConfirmResponse:
        request = DispenseConfirmRequest(
            medicine_id=command.medicine_id,
            slot=command.slot,
            quantity=command.quantity,
            reason="普通库存个人用药安全核查通过",
            confirmed_safety_notice=True,
            confirm_real_dispense=True,
            target_user_id=command.service_user_id,
            target_user_name=command.service_user_name,
            verification_method=command.verification_method,
            expected_review_fingerprint=command.expected_review_fingerprint,
        )
        return self._confirm(
            request,
            validated_manual=True,
            qsm_operation_id=command.qsm_operation_id,
            manual_execution=command,
        )

    def confirm_debug_dry_run(
        self,
        request: DispenseConfirmRequest,
    ) -> DispenseConfirmResponse:
        """Explicit device-console adapter; it can never request a real cabinet action."""
        return self._confirm(request, force_dry_run=True, debug_dry_run=True)

    def _confirm(
        self,
        request: DispenseConfirmRequest,
        force_dry_run: bool | None = None,
        *,
        validated_manual: bool = False,
        debug_dry_run: bool = False,
        qsm_operation_id: str = "",
        manual_execution: ManualDispenseExecutionCommand | None = None,
    ) -> DispenseConfirmResponse:
        medicine = self.medicine_repository.get_by_id(request.medicine_id)
        if medicine is None:
            raise DispenseError("未找到该药品。", status_code=404)
        if request.slot != medicine.slot:
            raise DispenseError("药品身份与当前库存记录不一致。")
        if request.confirmed_safety_notice is not True:
            raise DispenseError("请先阅读并确认药品说明与安全提示。")
        if medicine.guidance_source == "pending":
            raise DispenseError("该药品资料尚未补全，完成实物包装和说明书核验前不可取药。")
        if not medicine.package_verified:
            raise DispenseError("该药品包装规格尚未人工核验，核验完成前不可取药。")
        if (request.verification_method == "inquiry_confirmed" or validated_manual) and (
            medicine.safety_review_status != "reviewed"
            or not medicine.safety_reviewed_by.strip()
            or not medicine.safety_reviewed_at.strip()
        ):
            raise DispenseError("该药品安全资料尚未完成审核，审核完成前不可取药。")
        if MedicineKnowledgeRepository.is_expired(medicine.expire_date):
            raise DispenseError("该药品已过有效期，不可取药；请联系管理员更换库存。")
        if medicine.stock < request.quantity:
            raise DispenseError("当前库存不足，不能执行取药。", status_code=409)
        if (
            not medicine.is_otc
            and not request.today_plan_id
            and not validated_manual
            and not debug_dry_run
        ):
            raise DispenseError("该药品需凭处方或既往用药计划取用，请先完成医生审核。")
        canonical_name, target_user_type, persona_generation = self._resolve_identity(
            request.target_user_id,
            request.target_user_name,
        )
        registered_allergies = self._registered_allergies(request.target_user_id)
        if registered_allergies and MedicineKnowledgeRepository.has_allergy_conflict(
            medicine,
            registered_allergies,
        ):
            raise DispenseError(
                f"已登记的用药禁忌（{registered_allergies}）与{medicine.name}冲突，不可取药。"
            )
        request = request.model_copy(update={"target_user_name": canonical_name})
        plan_records_service = None
        if request.today_plan_id:
            from .records_service import RecordsService

            plan_records_service = RecordsService()
            try:
                pending_plan_operation = (
                    plan_records_service.pending_plan_dispense_operation(
                        request.today_plan_id,
                        request.medicine_id,
                        request.target_user_id,
                    )
                )
                if not pending_plan_operation:
                    plan_records_service.validate_dispense_plan(
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
        if (
            (request.verification_method == "inquiry_confirmed" or validated_manual)
            and not request.expected_review_fingerprint.strip()
        ):
            raise DispenseError(
                "问询方案缺少当前审核凭据，请返回结果页重新核对后再取药。",
                status_code=409,
            )
        if request.expected_review_fingerprint:
            if (
                MedicineKnowledgeRepository.review_fingerprint(latest)
                != request.expected_review_fingerprint
            ):
                raise DispenseError(
                    "药品身份或安全资料已变化，请重新核对后再取药。",
                    status_code=409,
                )
        if validated_manual:
            if manual_execution is None:
                raise DispenseError("普通库存取药缺少最终安全核查凭据。", status_code=409)
            self._validate_manual_execution_snapshot(manual_execution, latest)
        medicine = latest
        dry_run = self._should_dry_run(request, medicine, force_dry_run)
        if (
            not dry_run
            and request.verification_method.strip() == "inquiry_confirmed"
            and not request.request_id.strip()
        ):
            raise DispenseError(
                "问询取药缺少稳定动作标识，本次分类柜指示灯未亮；请返回原问询会话重试。",
                status_code=409,
            )
        if validated_manual and not dry_run:
            if manual_execution is None:
                raise DispenseError(
                    "药品库存记录已经变化，请重新核查。",
                    status_code=409,
                )
            try:
                ManualMedicationAccessRepository().reserve_checked_execution(
                    manual_execution
                )
            except ManualExecutionPreconditionError as exc:
                raise DispenseError(str(exc), status_code=409) from exc
        inventory_token = None
        if not dry_run:
            inventory_token = self.medicine_repository.get_inventory_observation_token(
                medicine.id
            )
            if inventory_token is None:
                raise DispenseError(
                    "药品库存记录已变化，本次分类柜指示灯未亮。",
                    status_code=409,
                )
        try:
            cabinet = cabinet_for_medicine_id(medicine.id)
        except CabinetMappingError as exc:
            raise DispenseError(str(exc), status_code=409) from exc
        qsm_cabinet_id = cabinet.id
        if (
            not qsm_operation_id
            and request.today_plan_id.strip()
            and not dry_run
        ):
            if plan_records_service is None:
                from .records_service import RecordsService

                plan_records_service = RecordsService()
            try:
                qsm_operation_id = plan_records_service.reserve_plan_dispense_operation(
                    request.today_plan_id,
                    request.medicine_id,
                    request.target_user_id,
                )
            except ValueError as exc:
                raise DispenseError(str(exc), status_code=409) from exc
        elif (
            not qsm_operation_id
            and request.verification_method.strip() == "inquiry_confirmed"
            and request.request_id.strip()
        ):
            qsm_operation_id = self._inquiry_operation_id(request.request_id)
        if qsm_operation_id:
            qsm_result = self.qsm_client.dispense(
                qsm_cabinet_id,
                request.quantity,
                dry_run=dry_run,
                operation_id=qsm_operation_id,
            )
        else:
            qsm_result = self.qsm_client.dispense(
                qsm_cabinet_id,
                request.quantity,
                dry_run=dry_run,
            )
        qsm_ok = bool(qsm_result.get("ok"))
        result_unknown = bool(qsm_result.get("result_unknown"))
        retry_safe = bool(qsm_result.get("retry_safe", not result_unknown))
        qsm_detail = str(qsm_result.get("detail") or qsm_result.get("error_message") or "")
        if not dry_run and (not qsm_ok or result_unknown):
            if result_unknown:
                message = "分类柜亮灯结果待现场确认，请勿自动重试。"
            else:
                message = f"分类柜指示灯未能点亮：{qsm_detail or '未返回成功状态'}"
            if request.today_plan_id and qsm_operation_id:
                if plan_records_service is None:
                    from .records_service import RecordsService

                    plan_records_service = RecordsService()
                try:
                    plan_records_service.mark_plan_dispense_operation(
                        request.today_plan_id,
                        qsm_operation_id,
                        "result_unknown" if result_unknown else "failed",
                    )
                except ValueError:
                    result_unknown = True
                    retry_safe = False
                    message = "分类柜亮灯结果待现场确认，请勿自动重试。"
            record = self._build_record(
                request,
                medicine,
                dry_run,
                message,
                qsm_ok=False,
                qsm_detail=qsm_detail,
                target_user_type=target_user_type,
                persona_generation=persona_generation,
            )
            self.dispense_repository.append(record)
            self._archive_identity_if_requested(request, record, target_user_type)
            return DispenseConfirmResponse(
                ok=False,
                dry_run=False,
                message=message,
                record_id=record.id,
                qsm_detail=qsm_detail,
                result_unknown=result_unknown,
                retry_safe=retry_safe,
                cabinet_id=cabinet.id,
                cabinet_label=cabinet.label,
            )

        message = (
            "本地测试记录已保存，未点亮分类柜指示灯。"
            if dry_run
            else f"{cabinet.id}号柜 · {cabinet.label}的指示灯已亮起，请自行打开亮灯的分类柜取药。"
        )
        record = self._build_record(
            request,
            medicine,
            dry_run,
            message,
            qsm_ok=qsm_ok,
            qsm_detail=qsm_detail,
            target_user_type=target_user_type,
            persona_generation=persona_generation,
        )
        inventory_observation_pending = False
        if not dry_run:
            _saved, inventory_observation_pending = (
                self.dispense_repository.append_with_inventory_observation(
                    record,
                    expected_stock=inventory_token.stock,
                    expected_inventory_revision=inventory_token.revision,
                )
            )
            if not inventory_observation_pending:
                message = (
                    "分类柜指示灯已亮；库存记录在亮灯期间已更新，"
                    "本次不再接受旧现场确认，请勿重复发起亮灯。"
                )
        else:
            self.dispense_repository.append(record)
        self._archive_identity_if_requested(request, record, target_user_type)
        if request.today_plan_id and not dry_run:
            from .records_service import RecordsService

            RecordsService().complete_today_plan(
                request.today_plan_id,
                request.medicine_id,
                request.target_user_id,
                dispense_operation_id=qsm_operation_id,
            )
        return DispenseConfirmResponse(
            ok=True,
            dry_run=dry_run,
            message=message,
            record_id=record.id,
            qsm_detail=qsm_detail,
            inventory_confirmation_required=inventory_observation_pending,
            cabinet_id=cabinet.id,
            cabinet_label=cabinet.label,
        )

    @staticmethod
    def _inquiry_operation_id(request_id: str) -> str:
        logical_action = f"inquiry-v1|{request_id.strip()}"
        return f"inquiry-{sha256(logical_action.encode('utf-8')).hexdigest()[:40]}"

    def _validate_manual_execution_snapshot(
        self,
        command: ManualDispenseExecutionCommand,
        medicine,
    ) -> None:
        person = ManualMedicationAccessRepository().get_person(command.service_user_id)
        if (
            person is None
            or person.archived
            or person.persona_generation != command.expected_persona_generation
            or person.safety_profile_revision != command.expected_safety_profile_revision
            or person.safety_fingerprint() != command.expected_person_safety_fingerprint
        ):
            raise DispenseError("人物资料已经更新，请重新确认身份并核查。", status_code=409)
        if (
            medicine.id != command.medicine_id
            or medicine.slot != command.slot
            or int(medicine.hardware_slot or 0) != command.expected_hardware_slot
        ):
            raise DispenseError("药品逻辑库存身份已经变化，请重新核查。", status_code=409)
        if medicine.stock != command.expected_stock:
            raise DispenseError("药品库存记录已经变化，请重新核查。", status_code=409)
        if (
            medicine.expire_date != command.expected_expire_date
            or MedicineKnowledgeRepository.is_expired(medicine.expire_date)
        ):
            raise DispenseError("药品有效期已经变化，请重新核查。", status_code=409)
        if (
            MedicineKnowledgeRepository.review_fingerprint(medicine)
            != command.expected_review_fingerprint
        ):
            raise DispenseError("药品身份或安全资料已经变化，请重新核查。", status_code=409)

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
        del request
        raise DispenseError(
            "旧版 1-23 仓位开柜能力已停用；请按药品执行现场安全取药，系统将点亮对应分类柜。",
            status_code=410,
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
        try:
            cabinet_id = str(cabinet_for_medicine_id(medicine.id).id)
        except CabinetMappingError as exc:
            raise DispenseError(str(exc), status_code=409) from exc
        if allowed_slot != cabinet_id:
            raise DispenseError("真实取药测试分类柜与当前药品分类柜不一致，已拒绝执行。")
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
        persona_generation: str,
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
            persona_generation=persona_generation,
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
    ) -> tuple[str, str, str]:
        user_id = str(target_user_id or "").strip()
        supplied_name = str(target_user_name or "").strip()
        if user_id:
            db.init_db()
            with db.connect() as conn:
                row = conn.execute(
                    """
                    SELECT name, status, persona_generation
                    FROM service_users
                    WHERE id=? AND archived=0
                    """,
                    (user_id,),
                ).fetchone()
            if row:
                status = str(row["status"] or "")
                user_type = "guest" if user_id.startswith("guest-") or status in {"访客", "游客"} else "registered"
                return (
                    str(row["name"]),
                    user_type,
                    str(row["persona_generation"] or ""),
                )
            if require_known:
                raise DispenseError("身份记录不存在，请重新进行指纹或面部确认。")
        if supplied_name:
            visitor = supplied_name.startswith(("访客", "游客"))
            return supplied_name, "guest" if visitor or not user_id else "registered", ""
        return "游客", "guest", ""

    @staticmethod
    def _registered_allergies(target_user_id: str) -> str:
        user_id = str(target_user_id or "").strip()
        if not user_id:
            return ""
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT allergies FROM service_users WHERE id=? AND archived=0",
                (user_id,),
            ).fetchone()
        return str(row["allergies"] or "").strip() if row else ""
