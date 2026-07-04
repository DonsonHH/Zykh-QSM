from __future__ import annotations

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.medicine import Medicine, MedicineListResponse, MedicineScanRegisterRequest, MedicineScanRegisterResponse


class MedicineService:
    def __init__(self, repository: MedicineRepository | None = None) -> None:
        self.repository = repository or MedicineRepository()

    def list_medicines(self) -> MedicineListResponse:
        medicines = self.repository.list_all()
        categories = ["全部"]
        for medicine in medicines:
            if medicine.category not in categories:
                categories.append(medicine.category)
        return MedicineListResponse(total=len(medicines), categories=categories, medicines=medicines)

    def get_medicine(self, medicine_id: str) -> Medicine | None:
        return self.repository.get_by_id(medicine_id)

    def register_scan_result(self, request: MedicineScanRegisterRequest) -> MedicineScanRegisterResponse:
        barcode = (request.barcode or "").strip()
        if barcode:
            existing = self.repository.get_by_barcode(barcode)
            if existing:
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
            name=name,
            spec=request.spec or "",
            expire_date=request.expire_date or "",
            stock=max(int(request.stock or 1), 1),
            unit=request.unit or "盒",
            category=request.category or "扫码录入",
            hardware_slot=slot,
            safety_note=request.safety_note or "",
        )
        return MedicineScanRegisterResponse(
            ok=True,
            created=True,
            message=f"已录入 {medicine.hardware_slot} 号仓，请在药品页核对库存与安全提示。",
            medicine=medicine,
        )
