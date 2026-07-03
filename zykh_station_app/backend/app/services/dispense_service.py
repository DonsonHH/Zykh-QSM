from __future__ import annotations

from uuid import uuid4

from ..config import settings
from ..db import now_text
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.medicine_repository import MedicineRepository
from ..schemas.dispense import DispenseConfirmRequest, DispenseConfirmResponse, DispenseRecord


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
    ) -> None:
        self.medicine_repository = medicine_repository or MedicineRepository()
        self.dispense_repository = dispense_repository or DispenseRepository()

    def confirm(self, request: DispenseConfirmRequest) -> DispenseConfirmResponse:
        medicine = self.medicine_repository.get_by_id(request.medicine_id)
        if medicine is None:
            raise DispenseError("未找到该药品。", status_code=404)
        if request.slot != medicine.slot:
            raise DispenseError("药品仓位与当前库存记录不一致。")
        if request.confirmed_safety_notice is not True:
            raise DispenseError("请先阅读并确认药品说明与安全提示。")
        if request.quantity > medicine.stock:
            raise DispenseError("库存不足，无法完成取药确认。")
        if settings.dispense_dry_run is not True:
            raise DispenseError("第二阶段仅支持 dry-run 取药确认，真实出药尚未启用。", status_code=409)

        record_id = f"dryrun-{uuid4().hex[:12]}"
        message = "dry-run 已记录，本阶段不会真实出药。"
        record = DispenseRecord(
            id=record_id,
            medicine_id=medicine.id,
            medicine_name=medicine.name,
            slot=medicine.slot,
            quantity=request.quantity,
            unit=medicine.unit,
            reason=request.reason,
            dry_run=True,
            message=message,
            created_at=now_text(),
        )
        self.dispense_repository.append(record)
        return DispenseConfirmResponse(ok=True, dry_run=True, message=message, record_id=record_id)

    def list_records(self) -> list[DispenseRecord]:
        return self.dispense_repository.list_records()
