from __future__ import annotations

from typing import Any

from .. import db
from ..repositories.medicine_repository import MedicineRepository
from ..schemas.medicine import Medicine
from .ai_service import AiService


class MedicineGuidanceService:
    def __init__(
        self,
        repository: MedicineRepository | None = None,
        ai_service: AiService | None = None,
    ) -> None:
        self.repository = repository or MedicineRepository()
        self.ai_service = ai_service or AiService()

    def enrich_medicine(self, medicine_id: str) -> Medicine | None:
        medicine = self.repository.get_by_id(medicine_id)
        if medicine is None:
            return None
        result = self.ai_service.generate_medicine_guidance(self._medicine_context(medicine))
        if not result.get("ok"):
            return medicine
        guidance = result.get("guidance")
        if not isinstance(guidance, dict):
            return medicine

        indications = self._text(guidance.get("indications"), 180)
        dosage = self._text(guidance.get("dosage"), 180)
        contraindications = self._items(guidance.get("contraindications"), 5, 100)
        safety_note = self._text(guidance.get("safety_note"), 160)
        if not indications or not dosage or not contraindications:
            return medicine

        return self.repository.update(
            medicine.id,
            {
                "indications": indications,
                "dosage": dosage,
                "contraindications": contraindications,
                "safety_note": safety_note or medicine.safety_note,
                "guidance_source": "cloud_ai",
                "guidance_review_required": True,
                "guidance_updated_at": db.now_text(),
            },
        )

    @staticmethod
    def _medicine_context(medicine: Medicine) -> dict[str, Any]:
        return {
            "name": medicine.name,
            "manufacturer": medicine.manufacturer,
            "barcode": medicine.barcode,
            "category": medicine.category,
        }

    @staticmethod
    def _text(value: object, limit: int) -> str:
        text = " ".join(str(value or "").strip().split())
        return text[:limit]

    @classmethod
    def _items(cls, value: object, count: int, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for raw in value:
            item = cls._text(raw, limit)
            if item and item not in items:
                items.append(item)
            if len(items) >= count:
                break
        return items
