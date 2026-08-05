from __future__ import annotations

from datetime import date
import re

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.inquiry import CandidateMedicine, TreatmentMedicine, TreatmentOption
from ..schemas.medicine import Medicine


class MedicineKnowledgeRepository:
    """Builds and validates the inquiry-only medicine safety pool."""

    def __init__(self, medicine_repository: MedicineRepository | None = None) -> None:
        self.medicine_repository = medicine_repository or MedicineRepository()

    def safe_candidate_pool(
        self,
        context_text: str,
        *,
        existing_direction_ids: set[str] | None = None,
    ) -> list[CandidateMedicine]:
        directed_ids = existing_direction_ids or set()
        candidates: list[CandidateMedicine] = []
        for medicine in self.medicine_repository.list_all():
            if not self._eligible(medicine, context_text, directed_ids):
                continue
            if not medicine.indications.strip() or not medicine.dosage.strip():
                continue
            if medicine.guidance_source == "pending":
                continue
            candidates.append(
                CandidateMedicine(
                    id=medicine.id,
                    name=medicine.name,
                    category=medicine.category,
                    slot=str(medicine.hardware_slot or medicine.slot),
                    stock=medicine.stock,
                    unit=medicine.unit,
                    safety_note=medicine.safety_note,
                    indications=medicine.indications,
                    dosage=medicine.dosage,
                    match_reason="",
                    requires_existing_direction=not medicine.is_otc,
                )
            )
        return candidates

    def options_from_ai_selection(
        self,
        payload: dict,
        safe_pool: list[CandidateMedicine],
    ) -> list[TreatmentOption]:
        """Accept at most two model options and reject every ID outside the safe pool."""
        allowed = {candidate.id: candidate for candidate in safe_pool}
        options: list[TreatmentOption] = []
        used_signatures: set[tuple[str, ...]] = set()
        raw_options = payload.get("options") if isinstance(payload, dict) else []
        if not isinstance(raw_options, list):
            return []
        for raw in raw_options[:2]:
            if not isinstance(raw, dict):
                continue
            raw_ids = raw.get("medicine_ids")
            if not isinstance(raw_ids, list):
                continue
            selected: list[CandidateMedicine] = []
            for raw_id in raw_ids[:4]:
                candidate = allowed.get(str(raw_id or "").strip())
                if candidate is not None and candidate.id not in {item.id for item in selected}:
                    selected.append(candidate)
            if not selected:
                continue
            signature = tuple(candidate.id for candidate in selected)
            if signature in used_signatures:
                continue
            used_signatures.add(signature)
            option_id = "A" if not options else "B"
            label = self._clean_option_text(
                raw.get("label"),
                "主方案" if not options else "备选方案",
                20,
            )
            reason = self._clean_option_text(
                raw.get("reason"),
                "请结合当前不适和药品说明核对这一选择。",
                120,
            )
            raw_usage = raw.get("usage_by_medicine")
            usage_by_medicine = raw_usage if isinstance(raw_usage, dict) else {}
            options.append(
                TreatmentOption(
                    option_id=option_id,
                    label=label,
                    when=reason,
                    medicines=[
                        TreatmentMedicine(
                            **candidate.model_dump(),
                            role="主要选择" if index == 0 else "按顺序配合",
                            covered_symptoms=[],
                            recommended_usage=self._safe_recommended_usage(
                                usage_by_medicine.get(candidate.id),
                                candidate.dosage,
                            ),
                        )
                        for index, candidate in enumerate(selected)
                    ],
                )
            )
        return options

    @staticmethod
    def _clean_option_text(value: object, fallback: str, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        for phrase in ("覆盖症状", "库存核验", "独立备选", "互斥方案"):
            text = text.replace(phrase, "")
        return (text or fallback)[:limit]

    @classmethod
    def _safe_recommended_usage(cls, value: object, label_dosage: str) -> str:
        """Keep model wording only when its quantities stay within the label text."""
        text = re.sub(r"\s+", " ", str(value or "")).strip(" ，。；;")
        if not text:
            return label_dosage
        if any(
            phrase in text
            for phrase in ("加倍", "增加剂量", "超过说明", "多服", "自行调整", "替代医嘱")
        ):
            return label_dosage
        label_numbers = cls._number_tokens(label_dosage)
        suggested_numbers = cls._number_tokens(text)
        if any(number not in label_numbers for number in suggested_numbers):
            return label_dosage
        return text[:120]

    @staticmethod
    def _number_tokens(value: str) -> set[str]:
        translations = str.maketrans({"两": "二", "俩": "二"})
        return {
            token.translate(translations)
            for token in re.findall(r"\d+(?:\.\d+)?|[零一二两俩三四五六七八九十百半]+", value or "")
        }

    @staticmethod
    def _eligible(medicine: Medicine, context_text: str, directed_ids: set[str] | None = None) -> bool:
        has_existing_direction = medicine.id in (directed_ids or set())
        if medicine.stock <= 0:
            return False
        if not medicine.package_verified:
            return False
        if (not medicine.is_otc or medicine.category == "慢病常用") and not has_existing_direction:
            return False
        if MedicineKnowledgeRepository.is_expired(medicine.expire_date):
            return False
        return not MedicineKnowledgeRepository.has_allergy_conflict(medicine, context_text)

    @staticmethod
    def has_allergy_conflict(medicine: Medicine, context_text: str) -> bool:
        conflict_text = " ".join([medicine.name, *medicine.contraindications]).lower()
        allergies = MedicineKnowledgeRepository._allergy_terms(context_text)
        return any(
            allergy not in {"无", "没有", "不确定"} and len(allergy) >= 2 and allergy in conflict_text
            for allergy in allergies
        )

    @staticmethod
    def _allergy_terms(value: str) -> list[str]:
        terms: list[str] = []
        for raw in re.split(r"[\s,，、;；/]+", value.lower()):
            term = raw.strip()
            if re.search(r"(?:没有|并没有|没|无|否认).{0,6}(?:过敏|禁忌|不耐受)", term):
                continue
            for marker in (
                "药物过敏史", "过敏史", "不耐受史", "禁忌史",
                "药物过敏", "过敏", "禁忌", "不能使用", "不能用", "不耐受",
            ):
                term = term.replace(marker, "")
            term = re.sub(r"^(?:我|本人|患者)?(?:曾经|曾|有|对|存在|明确)+", "", term)
            term = re.sub(r"(?:类药物|药物|类|史|我|本人|患者|或|和|与|及)+$", "", term).strip()
            terms.extend(
                candidate
                for candidate in (
                    re.sub(r"(?:类药物|药物|类|史|我|本人|患者)+$", "", part).strip()
                    for part in re.split(r"[和与及或]+", term)
                )
                if candidate
            )
        return terms

    @staticmethod
    def is_expired(value: str, reference_date: date | None = None) -> bool:
        match = re.fullmatch(
            r"(\d{4})[-./](\d{1,2})(?:[-./](\d{1,2}))?",
            str(value or "").strip(),
        )
        if not match:
            return True
        try:
            year, month = int(match.group(1)), int(match.group(2))
            day = int(match.group(3)) if match.group(3) else None
            if day is not None:
                expires_on = date(year, month, day)
            else:
                # Month-only package dates remain valid through that calendar month.
                date(year, month, 1)
                expires_on = None
        except ValueError:
            return True
        today = reference_date or date.today()
        if expires_on is not None:
            return expires_on < today
        return (year, month) < (today.year, today.month)
