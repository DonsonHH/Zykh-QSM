from __future__ import annotations

from datetime import date
import re

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.inquiry import CandidateMedicine
from ..schemas.medicine import Medicine


DIMENSION_MEDICINE_IDS = {
    "感冒鼻部症状": ["slot-03-ganmao-qingre", "slot-01-fufang-ganmaoling", "slot-18-budesonide-nasal"],
    "发热全身不适": ["slot-01-fufang-ganmaoling", "slot-03-ganmao-qingre"],
    "咳嗽咳痰": ["slot-05-nin-jiom-pei-pa-koa", "slot-07-yinhuang"],
    "咽喉口腔不适": ["slot-07-yinhuang", "slot-11-guilin-xiguashuang"],
    "恶心暑湿": ["slot-08-huoxiang-zhengqi"],
    "腹泻肠道不适": ["slot-09-bifid-triple"],
    "便秘": ["slot-06-lactulose"],
    "胃酸胃部不适": ["slot-12-hydrotalcite"],
    "过敏瘙痒": ["slot-18-budesonide-nasal", "slot-23-desloratadine"],
    "轻微外伤": ["slot-17-iodophor", "slot-20-bandage", "slot-10-gauze", "slot-22-cotton-swab"],
    "皮肤真菌不适": ["slot-16-ketoconazole"],
    "肌肉关节疼痛": ["slot-19-ketoprofen-gel"],
    "干眼不适": ["slot-13-sodium-hyaluronate-eye"],
    "鼻炎过敏": ["slot-18-budesonide-nasal", "slot-23-desloratadine"],
    "营养补充": ["slot-02-centrum"],
}


class MedicineKnowledgeRepository:
    def __init__(self, medicine_repository: MedicineRepository | None = None) -> None:
        self.medicine_repository = medicine_repository or MedicineRepository()

    def candidates(
        self,
        dimensions: list[str],
        allergy_text: str,
    ) -> list[CandidateMedicine]:
        medicines = {medicine.id: medicine for medicine in self.medicine_repository.list_all()}
        scored: dict[str, tuple[int, str]] = {}
        for dimension_index, dimension in enumerate(dimensions):
            for medicine_index, medicine_id in enumerate(DIMENSION_MEDICINE_IDS.get(dimension, [])):
                score = 100 - (dimension_index * 10) - medicine_index
                if medicine_id not in scored or score > scored[medicine_id][0]:
                    scored[medicine_id] = (score, dimension)
        ranked: list[tuple[int, CandidateMedicine]] = []
        for medicine_id, (score, dimension) in scored.items():
            medicine = medicines.get(medicine_id)
            if medicine is None or not self._eligible(medicine, allergy_text):
                continue
            ranked.append((score, self._candidate(medicine, dimension)))
        ranked.sort(key=lambda item: (-item[0], int(item[1].slot)))
        return [candidate for _, candidate in ranked]

    @staticmethod
    def _eligible(medicine: Medicine, allergy_text: str) -> bool:
        if medicine.stock <= 0 or not medicine.is_otc or medicine.category == "慢病常用":
            return False
        if MedicineKnowledgeRepository._expired(medicine.expire_date):
            return False
        conflict_text = " ".join([medicine.name, *medicine.contraindications]).lower()
        allergies = MedicineKnowledgeRepository._allergy_terms(allergy_text)
        return not any(
            allergy not in {"无", "没有", "不确定"} and len(allergy) >= 2 and allergy in conflict_text
            for allergy in allergies
        )

    @staticmethod
    def _allergy_terms(value: str) -> list[str]:
        terms: list[str] = []
        for raw in re.split(r"[\s,，、;；/]+", value.lower()):
            term = raw.strip()
            for marker in ("药物过敏", "过敏", "禁忌", "不能使用", "不能用", "不耐受"):
                term = term.replace(marker, "")
            term = term.strip()
            if term:
                terms.append(term)
        return terms

    @staticmethod
    def _expired(value: str) -> bool:
        normalized = value.strip().replace(".", "-").replace("/", "-")
        parts = normalized.split("-")
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 12
        except (ValueError, IndexError):
            return True
        today = date.today()
        return (year, month) < (today.year, today.month)

    @staticmethod
    def _candidate(medicine: Medicine, dimension: str) -> CandidateMedicine:
        return CandidateMedicine(
            id=medicine.id,
            name=medicine.name,
            category=medicine.category,
            slot=str(medicine.hardware_slot or medicine.slot),
            stock=medicine.stock,
            unit=medicine.unit,
            safety_note=medicine.safety_note,
            match_reason=f"与{dimension}相关，仅供查看药品信息和安全提示。",
        )
