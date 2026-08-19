from __future__ import annotations

from ..repositories.dispense_repository import DispenseRepository
from ..repositories.medicine_repository import MedicineRepository
from ..schemas.medicine import (
    LocalMedicine,
    Medicine,
    MedicineCabinet,
    MedicineListResponse,
    MedicineScanRegisterRequest,
    MedicineScanRegisterResponse,
    MedicineUpdateRequest,
    MedicineUpdateResponse,
)
from .cabinet_v2_catalog import CabinetMappingError, cabinet_for_medicine_id, cabinet_groups
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
        medicines = [
            self._with_local_cabinet(self._with_dispense_count(item, counts))
            for item in self.repository.list_all()
        ]
        categories = ["全部"]
        for medicine in medicines:
            if medicine.category not in categories:
                categories.append(medicine.category)
        cabinets = [
            MedicineCabinet(
                id=group.id,
                label=group.label,
                description=group.description,
                medicine_ids=sorted(group.medicine_ids),
            )
            for group in cabinet_groups()
        ]
        return MedicineListResponse(
            total=len(medicines),
            categories=categories,
            cabinets=cabinets,
            medicines=medicines,
        )

    def get_medicine(self, medicine_id: str) -> LocalMedicine | None:
        medicine = self.repository.get_by_id(medicine_id)
        return (
            self._with_local_cabinet(self._with_dispense_count(medicine))
            if medicine is not None
            else None
        )

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
            message=f"药品信息已保存。{guidance_message}",
            medicine=medicine,
        )

    def register_scan_result(self, request: MedicineScanRegisterRequest) -> MedicineScanRegisterResponse:
        barcode = (request.barcode or "").strip()
        if barcode:
            existing = self.repository.get_by_barcode(barcode)
            if existing:
                existing = self._with_local_cabinet(self._with_dispense_count(existing))
                return MedicineScanRegisterResponse(
                    ok=True,
                    created=False,
                    message="该条码已存在，已打开现有药品信息。",
                    medicine=existing,
                )

        return MedicineScanRegisterResponse(
            ok=False,
            created=False,
            message=(
                "三分类柜版本不自动新建未映射药品；请先完成药品档案与分类柜映射配置。"
            ),
            medicine=None,
        )

    def _with_dispense_count(
        self,
        medicine: Medicine,
        counts: dict[str, int] | None = None,
    ) -> Medicine:
        history = counts if counts is not None else self.dispense_repository.successful_counts_by_medicine()
        return medicine.model_copy(update={"dispense_count": history.get(medicine.id, 0)})

    @staticmethod
    def _with_local_cabinet(medicine: Medicine) -> LocalMedicine:
        try:
            cabinet = cabinet_for_medicine_id(medicine.id)
        except CabinetMappingError:
            return LocalMedicine(**medicine.model_dump())
        return LocalMedicine(
            **medicine.model_dump(),
            cabinet_id=cabinet.id,
            cabinet_label=cabinet.label,
            cabinet_description=cabinet.description,
        )
