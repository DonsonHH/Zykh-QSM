from __future__ import annotations

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.medicine import Medicine, MedicineListResponse


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
