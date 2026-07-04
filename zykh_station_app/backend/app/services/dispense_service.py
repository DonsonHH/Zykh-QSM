from __future__ import annotations

from uuid import uuid4

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


class DispenseError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DispenseService:
    def __init__(
        self,
        medicine_repository: MedicineRepository | None = None,
        dispense_repository: DispenseRepository | None = None,
        qsm_client: QsmClient | None = None,
    ) -> None:
        self.medicine_repository = medicine_repository or MedicineRepository()
        self.dispense_repository = dispense_repository or DispenseRepository()
        self.qsm_client = qsm_client or QsmClient()

    def confirm(self, request: DispenseConfirmRequest, force_dry_run: bool | None = None) -> DispenseConfirmResponse:
        medicine = self.medicine_repository.get_by_id(request.medicine_id)
        if medicine is None:
            raise DispenseError("未找到该药品。", status_code=404)
        if request.slot != medicine.slot:
            raise DispenseError("药品仓位与当前库存记录不一致。")
        if request.confirmed_safety_notice is not True:
            raise DispenseError("请先阅读并确认药品说明与安全提示。")
        if request.quantity > medicine.stock:
            raise DispenseError("库存不足，无法完成取药确认。")
        dry_run = self._should_dry_run(request, medicine, force_dry_run)
        qsm_result = self.qsm_client.dispense(str(medicine.hardware_slot or medicine.slot), request.quantity, dry_run=dry_run)
        qsm_ok = bool(qsm_result.get("ok"))
        qsm_detail = str(qsm_result.get("detail") or qsm_result.get("error_message") or "")
        if not dry_run and not qsm_ok:
            message = f"外设开柜失败：{qsm_detail or '未返回成功状态'}"
            record = self._build_record(request, medicine, dry_run, message, qsm_ok=False, qsm_detail=qsm_detail)
            self.dispense_repository.append(record)
            return DispenseConfirmResponse(ok=False, dry_run=False, message=message, record_id=record.id, qsm_detail=qsm_detail)

        message = "本地测试记录已保存，未打开柜门。" if dry_run else "取药确认已完成，柜门已打开。"
        record = self._build_record(request, medicine, dry_run, message, qsm_ok=qsm_ok, qsm_detail=qsm_detail)
        self.dispense_repository.append(record)
        if not dry_run:
            self.medicine_repository.decrement_stock(medicine.id, request.quantity)
        return DispenseConfirmResponse(ok=True, dry_run=dry_run, message=message, record_id=record.id, qsm_detail=qsm_detail)

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
            created_at=now_text(),
        )
