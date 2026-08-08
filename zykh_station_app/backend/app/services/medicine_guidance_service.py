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
        if not all(
            field in guidance
            for field in ("aliases", "active_ingredients", "structured_contraindications")
        ):
            return medicine

        indications = self._text(guidance.get("indications"), 180)
        dosage = self._text(guidance.get("dosage"), 180)
        contraindications = self._items(guidance.get("contraindications"), 5, 100)
        aliases = self._items(guidance.get("aliases"), 8, 60)
        active_ingredients = self._items(guidance.get("active_ingredients"), 8, 60)
        structured_contraindications = self._structured_items(
            guidance.get("structured_contraindications"),
            count=8,
        )
        safety_note = self._text(guidance.get("safety_note"), 160)
        if not indications or not dosage or not contraindications:
            return medicine

        return self.repository.update(
            medicine.id,
            {
                "indications": indications,
                "dosage": dosage,
                "contraindications": contraindications,
                "aliases": aliases,
                "active_ingredients": active_ingredients,
                "structured_contraindications": structured_contraindications,
                "safety_note": safety_note or medicine.safety_note,
                "guidance_source": "cloud_ai",
                "guidance_review_required": True,
                "guidance_updated_at": db.now_text(),
                "safety_review_status": "draft",
                "safety_reviewed_by": "",
                "safety_reviewed_at": "",
            },
        )

    @staticmethod
    def _medicine_context(medicine: Medicine) -> dict[str, Any]:
        return {
            "name": medicine.name,
            "manufacturer": medicine.manufacturer,
            "barcode": medicine.barcode,
            "category": medicine.category,
            "spec": medicine.spec,
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

    @classmethod
    def _structured_items(cls, value: object, *, count: int) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, str]] = []
        for raw in value:
            if not isinstance(raw, dict):
                continue
            concept_code = cls._text(raw.get("concept_code"), 60)
            display_text = cls._text(raw.get("display_text"), 120)
            item = {"concept_code": concept_code, "display_text": display_text}
            if concept_code and display_text and item not in items:
                items.append(item)
            if len(items) >= count:
                break
        return items
