from __future__ import annotations

from ..repositories.dispense_repository import DispenseRepository
from ..repositories.medicine_repository import MedicineRepository
from ..schemas.medicine import (
    Medicine,
    MedicineListResponse,
    MedicineScanRegisterRequest,
    MedicineScanRegisterResponse,
    MedicineUpdateRequest,
    MedicineUpdateResponse,
)
from .medicine_guidance_service import MedicineGuidanceService


class MedicineService:
    GUIDANCE_BASE_FIELDS = {"name", "manufacturer", "barcode", "category", "spec"}
    GUIDANCE_CONTENT_FIELDS = {
        "tags",
        "aliases",
        "active_ingredients",
        "indications",
        "dosage",
        "contraindications",
        "structured_contraindications",
        "safety_note",
        "is_otc",
        "is_emergency",
    }

    def __init__(
        self,
        repository: MedicineRepository | None = None,
        guidance_service: MedicineGuidanceService | None = None,
        dispense_repository: DispenseRepository | None = None,
    ) -> None:
        self.repository = repository or MedicineRepository()
        self.guidance_service = guidance_service or MedicineGuidanceService(repository=self.repository)
        self.dispense_repository = dispense_repository or DispenseRepository()

    def list_medicines(self) -> MedicineListResponse:
        counts = self.dispense_repository.successful_counts_by_medicine()
        medicines = [self._with_dispense_count(item, counts) for item in self.repository.list_all()]
        categories = ["全部"]
        for medicine in medicines:
            if medicine.category not in categories:
                categories.append(medicine.category)
        return MedicineListResponse(total=len(medicines), categories=categories, medicines=medicines)

    def get_medicine(self, medicine_id: str) -> Medicine | None:
        medicine = self.repository.get_by_id(medicine_id)
        return self._with_dispense_count(medicine) if medicine is not None else None

    def update_medicine(self, medicine_id: str, request: MedicineUpdateRequest) -> MedicineUpdateResponse | None:
        current = self.repository.get_by_id(medicine_id)
        if current is None:
            return None
        if hasattr(request, "model_dump"):
            updates = request.model_dump(exclude_unset=True)
        else:
            updates = request.dict(exclude_unset=True)
        base_changed = any(
            key in updates and updates[key] is not None and updates[key] != getattr(current, key)
            for key in self.GUIDANCE_BASE_FIELDS
        )
        guidance_changed = any(key in updates for key in self.GUIDANCE_CONTENT_FIELDS)
        if base_changed:
            updates.update(
                guidance_source="pending",
                guidance_review_required=True,
                guidance_updated_at="",
            )
            updates.setdefault("package_verified", False)
        elif guidance_changed:
            updates.update(
                guidance_source="manual",
                guidance_review_required=True,
            )
        medicine = self.repository.update(medicine_id, updates)
        if medicine is None:
            return None
        if base_changed:
            medicine = self.guidance_service.enrich_medicine(medicine.id) or medicine
        medicine = self._with_dispense_count(medicine)
        guidance_message = "药品说明资料需核对实物包装。" if medicine.guidance_review_required else ""
        return MedicineUpdateResponse(
            ok=True,
            message=f"{medicine.hardware_slot}号柜药品信息已保存。{guidance_message}",
            medicine=medicine,
        )

    def register_scan_result(self, request: MedicineScanRegisterRequest) -> MedicineScanRegisterResponse:
        barcode = (request.barcode or "").strip()
        if barcode:
            existing = self.repository.get_by_barcode(barcode)
            if existing:
                existing = self._with_dispense_count(existing)
                return MedicineScanRegisterResponse(
                    ok=True,
                    created=False,
                    message=f"该条码已在 {existing.hardware_slot} 号仓，已打开现有药品信息。",
                    medicine=existing,
                )

        filled_slots = {medicine.hardware_slot for medicine in self.repository.list_all() if medicine.stock > 0}
        if len(filled_slots) >= 23 and not request.slot:
            return MedicineScanRegisterResponse(ok=False, created=False, message="23 个仓位已有库存，请先整理空仓。", medicine=None)

        slot = request.slot
        if slot is not None and (slot < 1 or slot > 23):
            return MedicineScanRegisterResponse(ok=False, created=False, message="仓位编号需在 1 到 23 之间。", medicine=None)
        if slot is not None and slot in filled_slots:
            return MedicineScanRegisterResponse(ok=False, created=False, message=f"{slot} 号仓已有库存，请在药品页选择空仓。", medicine=None)

        name = (request.name or "").strip() or ("待核验药品" if barcode else "")
        if not name:
            return MedicineScanRegisterResponse(ok=False, created=False, message="未识别到药品名称或条码，不能自动录入。", medicine=None)

        medicine = self.repository.create_from_scan(
            barcode=barcode,
            manufacturer=request.manufacturer or "",
            name=name,
            spec=request.spec or "",
            expire_date=request.expire_date or "",
            stock=max(int(request.stock or 1), 1),
            unit=request.unit or "盒",
            category=request.category or "扫码录入",
            indications=request.indications or "",
            dosage=request.dosage or "",
            hardware_slot=slot,
            safety_note=request.safety_note or "",
        )
        medicine = self.guidance_service.enrich_medicine(medicine.id) or medicine
        medicine = self._with_dispense_count(medicine)
        return MedicineScanRegisterResponse(
            ok=True,
            created=True,
            message=f"已录入 {medicine.hardware_slot} 号仓，请核对药品说明、用法用量与安全提示。",
            medicine=medicine,
        )

    def _with_dispense_count(
        self,
        medicine: Medicine,
        counts: dict[str, int] | None = None,
    ) -> Medicine:
        history = counts if counts is not None else self.dispense_repository.successful_counts_by_medicine()
        return medicine.model_copy(update={"dispense_count": history.get(medicine.id, 0)})
