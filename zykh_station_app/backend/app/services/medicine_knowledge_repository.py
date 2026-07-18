from __future__ import annotations

from datetime import date
import re

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.inquiry import CandidateMedicine, TreatmentMedicine, TreatmentOption
from ..schemas.medicine import Medicine


DIMENSION_MEDICINE_IDS = {
    "感冒鼻部症状": ["slot-03-ganmao-qingre", "slot-01-fufang-ganmaoling", "slot-18-budesonide-nasal", "slot-14-oseltamivir"],
    "发热全身不适": ["slot-01-fufang-ganmaoling", "slot-03-ganmao-qingre", "slot-14-oseltamivir"],
    "咳嗽咳痰": ["slot-05-nin-jiom-pei-pa-koa", "slot-07-yinhuang", "slot-04-amoxicillin"],
    "咽喉口腔不适": ["slot-07-yinhuang", "slot-11-guilin-xiguashuang", "slot-04-amoxicillin"],
    "恶心暑湿": ["slot-08-huoxiang-zhengqi"],
    "腹泻肠道不适": ["slot-09-bifid-triple"],
    "便秘": ["slot-06-lactulose"],
    "胃酸胃部不适": ["slot-12-hydrotalcite"],
    "过敏瘙痒": ["slot-18-budesonide-nasal", "slot-23-desloratadine"],
    "轻微外伤": ["slot-17-iodophor", "slot-20-bandage", "slot-10-gauze", "slot-22-cotton-swab", "slot-15-mupirocin"],
    "皮肤真菌不适": ["slot-16-ketoconazole"],
    "肌肉关节疼痛": ["slot-19-ketoprofen-gel"],
    "干眼不适": ["slot-13-sodium-hyaluronate-eye"],
    "鼻炎过敏": ["slot-18-budesonide-nasal", "slot-23-desloratadine"],
    "营养补充": ["slot-02-centrum"],
    "慢病既往用药": ["slot-21-amlodipine"],
}

COMBINATION_GROUPS = {
    "slot-01-fufang-ganmaoling": "systemic-cold",
    "slot-03-ganmao-qingre": "systemic-cold",
    "slot-05-nin-jiom-pei-pa-koa": "cough-relief",
    "slot-07-yinhuang": "systemic-throat",
    "slot-11-guilin-xiguashuang": "local-throat",
    "slot-10-gauze": "wound-cover",
    "slot-20-bandage": "wound-cover",
    "slot-17-iodophor": "wound-disinfect",
    "slot-22-cotton-swab": "wound-cleaning-tool",
}

WOUND_STAGE_ORDER = {
    "slot-22-cotton-swab": 1,
    "slot-17-iodophor": 2,
    "slot-20-bandage": 3,
    "slot-10-gauze": 3,
}

FEATURE_MEDICINE_WEIGHTS = {
    "清稀鼻涕": {"slot-03-ganmao-qingre": 34, "slot-01-fufang-ganmaoling": -14},
    "黄稠鼻涕": {"slot-01-fufang-ganmaoling": 30, "slot-03-ganmao-qingre": -12},
    "鼻痒喷嚏": {
        "slot-18-budesonide-nasal": 34,
        "slot-23-desloratadine": 26,
        "slot-01-fufang-ganmaoling": -18,
        "slot-03-ganmao-qingre": -18,
    },
    "明显畏寒": {"slot-03-ganmao-qingre": 28, "slot-01-fufang-ganmaoling": -8},
    "明显口渴": {"slot-01-fufang-ganmaoling": 24, "slot-03-ganmao-qingre": -8},
    "咽喉疼痛": {"slot-07-yinhuang": 30, "slot-11-guilin-xiguashuang": 22},
    "干咳": {"slot-05-nin-jiom-pei-pa-koa": 26},
    "有痰咳嗽": {"slot-05-nin-jiom-pei-pa-koa": 18, "slot-07-yinhuang": 8},
    "黄痰": {"slot-07-yinhuang": 18},
    "口腔溃疡": {"slot-11-guilin-xiguashuang": 34},
    "腹泻": {"slot-09-bifid-triple": 32, "slot-08-huoxiang-zhengqi": 8},
    "便秘": {"slot-06-lactulose": 34},
    "反酸烧心": {"slot-12-hydrotalcite": 34},
    "恶心呕吐": {"slot-08-huoxiang-zhengqi": 26},
    "皮肤瘙痒": {"slot-23-desloratadine": 28},
    "皮肤破损": {"slot-22-cotton-swab": 22, "slot-17-iodophor": 24, "slot-20-bandage": 20},
    "伤口红肿渗液": {"slot-15-mupirocin": 30},
    "肌肉关节疼痛": {"slot-19-ketoprofen-gel": 34},
    "眼干眼涩": {"slot-13-sodium-hyaluronate-eye": 34},
}


class MedicineKnowledgeRepository:
    def __init__(self, medicine_repository: MedicineRepository | None = None) -> None:
        self.medicine_repository = medicine_repository or MedicineRepository()

    def candidates(
        self,
        dimensions: list[str],
        allergy_text: str,
    ) -> list[CandidateMedicine]:
        return [candidate for _, _, candidate in self._ranked_candidates(dimensions, allergy_text)]

    def treatment_options(
        self,
        dimensions: list[str],
        context_text: str,
        *,
        symptom_features: list[str] | None = None,
        history_medicine_counts: dict[str, int] | None = None,
        limit: int = 2,
    ) -> list[TreatmentOption]:
        ranked = self._ranked_candidates(
            dimensions,
            context_text,
            symptom_features=symptom_features,
            history_medicine_counts=history_medicine_counts,
        )
        primary = self._select_combination(ranked, dimensions)
        if not primary:
            return []
        alternatives = self._alternative_combinations(ranked, dimensions, primary, limit=max(0, limit - 1))
        plans = [primary, *alternatives]
        return [
            self._serialize_plan(
                plan,
                option_id=chr(ord("A") + index),
                label="优先方案" if index == 0 else f"替代方案 {index}",
                dimensions=dimensions,
            )
            for index, plan in enumerate(plans[:limit])
        ]

    def _ranked_candidates(
        self,
        dimensions: list[str],
        context_text: str,
        *,
        symptom_features: list[str] | None = None,
        history_medicine_counts: dict[str, int] | None = None,
    ) -> list[tuple[int, list[str], CandidateMedicine]]:
        symptom_features = symptom_features or []
        history_medicine_counts = history_medicine_counts or {}
        medicines = {medicine.id: medicine for medicine in self.medicine_repository.list_all()}
        scored: dict[str, tuple[int, str]] = {}
        for dimension_index, dimension in enumerate(dimensions):
            for medicine_index, medicine_id in enumerate(DIMENSION_MEDICINE_IDS.get(dimension, [])):
                score = 100 - (dimension_index * 10) - medicine_index
                if medicine_id not in scored or score > scored[medicine_id][0]:
                    scored[medicine_id] = (score, dimension)
        ranked: list[tuple[int, list[str], CandidateMedicine]] = []
        for medicine_id, (score, dimension) in scored.items():
            medicine = medicines.get(medicine_id)
            if medicine is None or not self._eligible(medicine, context_text):
                continue
            coverage = [
                current_dimension
                for current_dimension in dimensions
                if medicine_id in DIMENSION_MEDICINE_IDS.get(current_dimension, [])
            ]
            if not medicine.is_otc:
                score -= 18
            if medicine.category == "慢病常用":
                score -= 12
            score += sum(
                FEATURE_MEDICINE_WEIGHTS.get(feature, {}).get(medicine_id, 0)
                for feature in symptom_features
            )
            # History is only a tie-breaker after current symptoms, stock and contraindications pass.
            score += min(max(int(history_medicine_counts.get(medicine_id, 0)), 0), 3) * 3
            ranked.append((score, coverage, self._candidate(medicine, dimension)))
        ranked.sort(key=lambda item: (-item[0], int(item[2].slot)))
        return ranked

    @staticmethod
    def _select_combination(
        ranked: list[tuple[int, list[str], CandidateMedicine]],
        dimensions: list[str],
    ) -> list[tuple[CandidateMedicine, list[str]]]:
        selected: list[tuple[CandidateMedicine, list[str]]] = []
        used_groups: set[str] = set()
        covered: set[str] = set()
        wound_flow = "轻微外伤" in dimensions
        for _, coverage, candidate in ranked:
            group = COMBINATION_GROUPS.get(candidate.id, candidate.id)
            if group in used_groups:
                continue
            is_wound_stage = wound_flow and candidate.id in WOUND_STAGE_ORDER
            if selected and not is_wound_stage and not (set(coverage) - covered):
                continue
            selected.append((candidate, coverage))
            used_groups.add(group)
            covered.update(coverage)
            if len(selected) >= 3:
                break
        if wound_flow:
            selected.sort(key=lambda item: WOUND_STAGE_ORDER.get(item[0].id, 99))
        return selected

    @classmethod
    def _alternative_combinations(
        cls,
        ranked: list[tuple[int, list[str], CandidateMedicine]],
        dimensions: list[str],
        primary: list[tuple[CandidateMedicine, list[str]]],
        *,
        limit: int,
    ) -> list[list[tuple[CandidateMedicine, list[str]]]]:
        if not primary or limit <= 0:
            return []
        required_coverage = cls._combination_coverage(primary)
        primary_ids = {candidate.id for candidate, _ in primary}
        seen = {tuple(candidate.id for candidate, _ in primary)}
        options: list[list[tuple[CandidateMedicine, list[str]]]] = []
        for replace_index, (current, current_coverage) in enumerate(primary):
            for _, coverage, candidate in ranked:
                if candidate.id in primary_ids or not (set(coverage) & set(current_coverage)):
                    continue
                variant = list(primary)
                variant[replace_index] = (candidate, coverage)
                groups = [COMBINATION_GROUPS.get(item.id, item.id) for item, _ in variant]
                if len(groups) != len(set(groups)) or not required_coverage.issubset(cls._combination_coverage(variant)):
                    continue
                if "轻微外伤" in dimensions:
                    variant.sort(key=lambda item: WOUND_STAGE_ORDER.get(item[0].id, 99))
                signature = tuple(item.id for item, _ in variant)
                if signature in seen:
                    continue
                seen.add(signature)
                options.append(variant)
                if len(options) >= limit:
                    return options
        return options

    @staticmethod
    def _combination_coverage(plan: list[tuple[CandidateMedicine, list[str]]]) -> set[str]:
        return {dimension for _, coverage in plan for dimension in coverage}

    @staticmethod
    def _serialize_plan(
        plan: list[tuple[CandidateMedicine, list[str]]],
        *,
        option_id: str,
        label: str,
        dimensions: list[str],
    ) -> TreatmentOption:
        medicines = [
            TreatmentMedicine(
                **candidate.model_dump(),
                role=MedicineKnowledgeRepository._plan_role(candidate.id, index),
                covered_symptoms=coverage,
            )
            for index, (candidate, coverage) in enumerate(plan)
        ]
        covered = list(dict.fromkeys(dimension for medicine in medicines for dimension in medicine.covered_symptoms))
        when = f"适合以{'、'.join(covered)}为主要表现时核对" if covered else "需结合当前症状进一步核对"
        return TreatmentOption(option_id=option_id, label=label, when=when, medicines=medicines)

    @staticmethod
    def _plan_role(medicine_id: str, index: int) -> str:
        if medicine_id == "slot-22-cotton-swab":
            return "清洁辅助"
        if medicine_id == "slot-17-iodophor":
            return "消毒处理"
        if medicine_id in {"slot-10-gauze", "slot-20-bandage"}:
            return "覆盖保护"
        return "主要对症" if index == 0 else "联合覆盖"

    @staticmethod
    def _eligible(medicine: Medicine, context_text: str) -> bool:
        if medicine.stock <= 0:
            return False
        if not medicine.is_otc or medicine.category == "慢病常用":
            return False
        if MedicineKnowledgeRepository._expired(medicine.expire_date):
            return False
        conflict_text = " ".join([medicine.name, *medicine.contraindications]).lower()
        allergies = MedicineKnowledgeRepository._allergy_terms(context_text)
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
            indications=medicine.indications,
            dosage=medicine.dosage,
            match_reason=(
                f"与{dimension}相关；该药需按既往医嘱核对后使用。"
                if not medicine.is_otc
                else f"与{dimension}相关，仅供查看药品信息和安全提示。"
            ),
            requires_existing_direction=not medicine.is_otc,
        )
