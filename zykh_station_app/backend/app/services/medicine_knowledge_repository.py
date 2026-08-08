from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.inquiry import CandidateMedicine, TreatmentMedicine, TreatmentOption
from ..schemas.medicine import Medicine


CHRONIC_CONDITION_TERMS_BY_CODE: dict[str, tuple[str, ...]] = {
    "diabetes": ("糖尿病", "高血糖", "血糖异常"),
    "renal_impairment": ("肾功能不全", "肾功能衰竭", "肾损害", "肾衰", "肾病"),
    "liver_impairment": ("肝功能不全", "肝功能受损", "肝损害", "肝病"),
    "hypercalcemia": ("高钙血症",),
    "hyperphosphatemia": ("高磷血症",),
    "hypophosphatemia": ("低磷血症",),
    "myasthenia_gravis": ("重症肌无力",),
    "galactose_intolerance": ("半乳糖不耐受",),
    "intestinal_obstruction": ("肠梗阻",),
    "peptic_ulcer": ("消化道溃疡", "胃溃疡"),
    "hypotension": ("低血压",),
    "pregnancy": ("孕妇", "怀孕", "妊娠"),
    "breastfeeding": ("哺乳",),
    "asthma": ("哮喘",),
}
CHRONIC_CONDITION_GROUPS: tuple[tuple[str, ...], ...] = tuple(
    CHRONIC_CONDITION_TERMS_BY_CODE.values()
)


@dataclass(frozen=True)
class MedicineSafetyContext:
    # ``context_text`` remains as a compatibility input for older callers.
    # New inquiry paths keep each source separate so a chronic condition cannot
    # be misreported as an allergy (or vice versa).
    context_text: str = ""
    history_text: str = ""
    allergy_text: str = ""
    used_medicines_text: str = ""
    relevance_text: str = ""
    existing_direction_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MedicineSafetyNotice:
    code: str
    message: str
    medicine_id: str = ""
    medicine_name: str = ""
    trigger: str = ""


@dataclass(frozen=True)
class CandidatePoolAssessment:
    candidates: list[CandidateMedicine]
    notices: list[MedicineSafetyNotice]


@dataclass(frozen=True)
class MedicineSelectionAssessment:
    options: list[TreatmentOption]
    notices: list[MedicineSafetyNotice]


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
        assessment = self.assess_candidates(
            MedicineSafetyContext(
                context_text=context_text,
                existing_direction_ids=frozenset(existing_direction_ids or set()),
            ),
            limit=1000,
        )
        return assessment.candidates

    def assess_candidates(
        self,
        context: MedicineSafetyContext,
        *,
        limit: int = 8,
    ) -> CandidatePoolAssessment:
        if limit <= 0:
            return CandidatePoolAssessment(candidates=[], notices=[])
        medicines = self.medicine_repository.list_all()
        by_id = {medicine.id: medicine for medicine in medicines}
        available = [
            self._candidate_from_medicine(medicine)
            for medicine in medicines
            if self._available(medicine, set(context.existing_direction_ids))
        ]
        if context.relevance_text.strip():
            related = self.focus_candidate_pool(
                context.relevance_text,
                available,
                limit=len(available),
            )
        else:
            related = available

        candidates: list[CandidateMedicine] = []
        notices: list[MedicineSafetyNotice] = []
        legacy_context = context.context_text
        used_context = context.used_medicines_text or legacy_context
        allergy_context = context.allergy_text or legacy_context
        history_context = context.history_text or legacy_context
        if context.used_medicines_text and not re.search(
            r"(?:本次)?已用药\s*[：:]", used_context, flags=re.IGNORECASE
        ):
            used_context = f"已用药：{used_context}"
        for candidate in related:
            medicine = by_id[candidate.id]
            used_reference = self._used_medicine_conflict_reference(
                medicine,
                used_context,
            )
            if used_reference:
                notices.append(
                    MedicineSafetyNotice(
                        code="used_medicine_duplicate",
                        message=(
                            f"你已说明本次用过“{used_reference}”；为避免重复用药，"
                            f"本次未推荐“{medicine.name}”。"
                        ),
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                        trigger=used_reference,
                    )
                )
                continue
            if self.has_allergy_conflict(medicine, allergy_context):
                notices.append(
                    MedicineSafetyNotice(
                        code="allergy_conflict",
                        message=f"根据已记录的过敏或禁忌信息，本次未推荐“{medicine.name}”。",
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                    )
                )
                continue
            if self.has_chronic_condition_conflict(medicine, history_context):
                notices.append(
                    MedicineSafetyNotice(
                        code="history_contraindication",
                        message=f"根据已记录的病史与药品禁忌，本次未推荐“{medicine.name}”。",
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                    )
                )
                continue
            if len(candidates) < limit:
                candidates.append(candidate)
        return CandidatePoolAssessment(candidates=candidates, notices=notices)

    @classmethod
    def _candidate_from_medicine(cls, medicine: Medicine) -> CandidateMedicine:
        facts = cls._safety_facts(medicine)
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
            tags=medicine.tags,
            contraindications=medicine.contraindications,
            aliases=list(facts["aliases"]),
            active_ingredients=list(facts["active_ingredients"]),
            review_fingerprint=cls.review_fingerprint(medicine),
            match_reason="",
            requires_existing_direction=not medicine.is_otc,
        )

    def options_from_ai_selection(
        self,
        payload: dict,
        safe_pool: list[CandidateMedicine],
    ) -> list[TreatmentOption]:
        """Compatibility wrapper for callers that only consume accepted options."""
        return self.validate_ai_selection(payload, safe_pool).options

    def validate_ai_selection(
        self,
        payload: dict,
        safe_pool: list[CandidateMedicine],
    ) -> MedicineSelectionAssessment:
        """Validate model selections without silently shortening unsafe combinations."""
        raw_options = payload.get("options") if isinstance(payload, dict) else []
        if not isinstance(raw_options, list):
            return MedicineSelectionAssessment(options=[], notices=[])
        allowed = {candidate.id: candidate for candidate in safe_pool}
        accepted_payloads: list[dict] = []
        notices: list[MedicineSafetyNotice] = []
        for raw in raw_options[:2]:
            if not isinstance(raw, dict):
                continue
            raw_ids = raw.get("medicine_ids")
            if not isinstance(raw_ids, list):
                continue
            if len(raw_ids) > 4:
                notices.append(
                    MedicineSafetyNotice(
                        code="combination_too_large",
                        message="一次组合最多包含 4 种药品，本次组合未被采用。",
                    )
                )
                continue
            normalized_ids = [str(raw_id or "").strip() for raw_id in raw_ids]
            if not normalized_ids or any(not medicine_id for medicine_id in normalized_ids):
                continue
            selected = [allowed[medicine_id] for medicine_id in normalized_ids if medicine_id in allowed]
            conflict_notice = self._ingredient_conflict_notice(selected)
            if len(normalized_ids) > 1 and conflict_notice is not None:
                notices.append(conflict_notice)
                continue
            if len(normalized_ids) > 1 and any(
                not candidate.active_ingredients
                and not self._is_controlled_non_drug_supply(candidate.id)
                for candidate in selected
            ):
                notices.append(
                    MedicineSafetyNotice(
                        code="combination_not_approved",
                        message="组合中存在有效成分资料不完整的药品，本次未被采用。",
                    )
                )
                continue
            if len(normalized_ids) > 1 and (
                len(set(normalized_ids)) != len(normalized_ids)
                or any(medicine_id not in allowed for medicine_id in normalized_ids)
                or not self._combination_is_approved(normalized_ids)
            ):
                notices.append(
                    MedicineSafetyNotice(
                        code="combination_not_approved",
                        message="该多药方案未命中药师审核的精确组合，本次未被采用。",
                    )
                )
                continue
            accepted_payloads.append(raw)
        return MedicineSelectionAssessment(
            options=self._options_from_model_payload(
                {"options": accepted_payloads},
                safe_pool,
            ),
            notices=notices,
        )

    def _is_controlled_non_drug_supply(self, medicine_id: str) -> bool:
        checker = getattr(
            self.medicine_repository,
            "is_controlled_non_drug_supply",
            None,
        )
        return bool(callable(checker) and checker(medicine_id))

    def _ingredient_conflict_notice(
        self,
        selected: list[CandidateMedicine],
    ) -> MedicineSafetyNotice | None:
        list_conflicts = getattr(
            self.medicine_repository,
            "list_reviewed_ingredient_conflicts",
            None,
        )
        matrix = {}
        if callable(list_conflicts):
            matrix = {
                tuple(
                    sorted(
                        (
                            self._compact(rule.left_ingredient),
                            self._compact(rule.right_ingredient),
                        )
                    )
                ): rule
                for rule in list_conflicts()
                if rule.disposition == "block"
            }
        for index, current in enumerate(selected):
            current_ingredients = {
                self._compact(ingredient): ingredient.strip()
                for ingredient in current.active_ingredients
                if self._compact(ingredient)
            }
            for other in selected[index + 1:]:
                other_ingredients = {
                    self._compact(ingredient): ingredient.strip()
                    for ingredient in other.active_ingredients
                    if self._compact(ingredient)
                }
                duplicate_keys = sorted(current_ingredients.keys() & other_ingredients.keys())
                if duplicate_keys:
                    ingredient = current_ingredients[duplicate_keys[0]]
                    return MedicineSafetyNotice(
                        code="ingredient_conflict",
                        message=f"组合中存在重复有效成分“{ingredient}”，本次未被采用。",
                        trigger=ingredient,
                    )
                for left_key, left_display in current_ingredients.items():
                    for right_key, right_display in other_ingredients.items():
                        rule = matrix.get(tuple(sorted((left_key, right_key))))
                        if rule is None:
                            continue
                        detail = rule.message.strip() or "药师审核的成分冲突矩阵禁止该组合"
                        return MedicineSafetyNotice(
                            code="ingredient_conflict",
                            message=(
                                f"“{left_display}”与“{right_display}”存在成分冲突："
                                f"{detail}，本次未被采用。"
                            ),
                            trigger=f"{left_display}+{right_display}",
                        )
        return None

    def _combination_is_approved(self, medicine_ids: list[str]) -> bool:
        list_combinations = getattr(
            self.medicine_repository,
            "list_reviewed_combinations",
            None,
        )
        if not callable(list_combinations):
            return False
        get_fingerprints = getattr(
            self.medicine_repository,
            "get_identity_fingerprints",
            None,
        )
        if not callable(get_fingerprints):
            return False
        current_fingerprints = get_fingerprints(medicine_ids)
        if set(current_fingerprints) != set(medicine_ids):
            return False
        expected = tuple(medicine_ids)
        return any(
            tuple(combination.medicine_ids) == expected
            and combination.member_identity_fingerprints == current_fingerprints
            for combination in list_combinations()
        )

    def _options_from_model_payload(
        self,
        payload: dict,
        safe_pool: list[CandidateMedicine],
    ) -> list[TreatmentOption]:
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
            if not self._combination_is_label_compatible(selected):
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
            raw_reasons = raw.get("reason_by_medicine")
            reason_by_medicine = raw_reasons if isinstance(raw_reasons, dict) else {}
            options.append(
                TreatmentOption(
                    option_id=option_id,
                    label=label,
                    when=reason,
                    medicines=[
                        TreatmentMedicine(
                            **{
                                **candidate.model_dump(),
                                "match_reason": self._clean_option_text(
                                    reason_by_medicine.get(candidate.id),
                                    reason,
                                    88,
                                ),
                            },
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

    @classmethod
    def focus_candidate_pool(
        cls,
        case_text: str,
        candidates: list[CandidateMedicine],
        *,
        limit: int = 8,
    ) -> list[CandidateMedicine]:
        """Retrieve a small relevant subset without making the medicine decision."""
        if not candidates or limit <= 0:
            return []
        query = re.sub(r"\s+", "", str(case_text or "").lower())
        query_ngrams = cls._text_ngrams(query)
        if not query_ngrams:
            return []
        scored: list[tuple[int, int, CandidateMedicine]] = []
        for index, candidate in enumerate(candidates):
            fields = [
                candidate.name,
                candidate.category,
                candidate.indications,
                *candidate.tags,
            ]
            document = re.sub(r"\s+", "", " ".join(fields).lower())
            overlap = len(query_ngrams & cls._text_ngrams(document))
            direct = sum(
                4
                for term in (candidate.category, *candidate.tags)
                if len(term.strip()) >= 2 and term.strip().lower() in query
            )
            scored.append((overlap + direct, -index, candidate))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not scored or scored[0][0] < 1:
            return []
        reliable_matches = [item for item in scored if item[0] >= 1]
        return [item[2] for item in reliable_matches[:limit]]

    @staticmethod
    def _text_ngrams(value: str) -> set[str]:
        compact = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value or "")
        return {
            compact[index:index + 2]
            for index in range(max(0, len(compact) - 1))
            if len(compact[index:index + 2]) == 2
        }

    @staticmethod
    def _combination_is_label_compatible(selected: list[CandidateMedicine]) -> bool:
        """Reject only combination conflicts that are explicit in local package metadata."""
        for index, current in enumerate(selected):
            current_ingredients = {
                MedicineKnowledgeRepository._compact(term)
                for term in current.active_ingredients
                if MedicineKnowledgeRepository._compact(term)
            }
            current_warnings = " ".join(current.contraindications)
            for other in selected[index + 1:]:
                other_ingredients = {
                    MedicineKnowledgeRepository._compact(term)
                    for term in other.active_ingredients
                    if MedicineKnowledgeRepository._compact(term)
                }
                if current_ingredients & other_ingredients:
                    return False
                other_warnings = " ".join(other.contraindications)
                pair = ((current, current_warnings, other), (other, other_warnings, current))
                for medicine, warnings, counterpart in pair:
                    if "同类" in warnings and medicine.category == counterpart.category:
                        return False
                    if "解热镇痛" in warnings and (
                        counterpart.category in {"解热镇痛", "感冒发热"}
                        or any(tag in {"退热", "头痛", "发热咽痛"} for tag in counterpart.tags)
                    ):
                        return False
                    if "抗菌药" in warnings and counterpart.category == "抗菌药":
                        return False
        return True

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
        if not MedicineKnowledgeRepository._available(medicine, directed_ids):
            return False
        if MedicineKnowledgeRepository._used_medicine_conflict(medicine, context_text):
            return False
        if MedicineKnowledgeRepository.has_chronic_condition_conflict(medicine, context_text):
            return False
        return not MedicineKnowledgeRepository.has_allergy_conflict(medicine, context_text)

    @staticmethod
    def _available(medicine: Medicine, directed_ids: set[str] | None = None) -> bool:
        has_existing_direction = medicine.id in (directed_ids or set())
        if medicine.stock <= 0:
            return False
        if not medicine.package_verified:
            return False
        if (
            medicine.safety_review_status != "reviewed"
            or not medicine.safety_reviewed_by.strip()
            or not medicine.safety_reviewed_at.strip()
        ):
            return False
        if (not medicine.is_otc or medicine.category == "慢病常用") and not has_existing_direction:
            return False
        if MedicineKnowledgeRepository.is_expired(medicine.expire_date):
            return False
        if not medicine.indications.strip() or not medicine.dosage.strip():
            return False
        if medicine.guidance_source == "pending":
            return False
        return True

    @classmethod
    def has_allergy_conflict(cls, medicine: Medicine, context_text: str) -> bool:
        facts = cls._safety_facts(medicine)
        conflict_text = cls._compact(
            " ".join(
                [
                    medicine.name,
                    *facts["aliases"],
                    *facts["active_ingredients"],
                    *medicine.contraindications,
                    *(
                        str(item.get("display_text") or "")
                        for item in medicine.structured_contraindications
                    ),
                ]
            )
        )
        allergies = MedicineKnowledgeRepository._allergy_terms(context_text)
        return any(
            allergy not in {"无", "没有", "不确定"}
            and len(cls._compact(allergy)) >= 2
            and cls._compact(allergy) in conflict_text
            for allergy in allergies
        )

    @classmethod
    def has_chronic_condition_conflict(cls, medicine: Medicine, context_text: str) -> bool:
        structured_codes = {
            str(item.get("concept_code") or "").strip()
            for item in medicine.structured_contraindications
        }
        if any(
            concept_code in structured_codes
            and any(cls._has_unnegated_term(context_text, term) for term in terms)
            for concept_code, terms in CHRONIC_CONDITION_TERMS_BY_CODE.items()
        ):
            return True
        warnings = cls._compact(" ".join(medicine.contraindications))
        return any(
            any(cls._has_unnegated_term(context_text, term) for term in group)
            and any(cls._compact(term) in warnings for term in group)
            for group in CHRONIC_CONDITION_GROUPS
        )

    @classmethod
    def _used_medicine_conflict(cls, medicine: Medicine, context_text: str) -> bool:
        return bool(cls._used_medicine_conflict_reference(medicine, context_text))

    @classmethod
    def _used_medicine_conflict_reference(
        cls,
        medicine: Medicine,
        context_text: str,
    ) -> str:
        matches = re.findall(
            r"(?:本次)?已用药\s*[：:]\s*([^；;\n]+)",
            str(context_text or ""),
            flags=re.IGNORECASE,
        )
        if not matches:
            return ""
        used_text = cls._compact(" ".join(matches))
        if not used_text or used_text in {"无", "没有", "未使用", "还没有"}:
            return ""
        facts = cls._safety_facts(medicine)
        references = (*facts["active_ingredients"], *facts["aliases"], medicine.name)
        return next(
            (
                value
                for value in references
                if len(cls._compact(value)) >= 2
                and cls._compact(value) in used_text
            ),
            "",
        )

    @staticmethod
    def _safety_facts(medicine: Medicine) -> dict[str, tuple[str, ...]]:
        aliases = tuple(
            dict.fromkeys(
                value.strip()
                for value in (medicine.name, *medicine.aliases)
                if value and value.strip()
            )
        )
        return {
            "aliases": aliases,
            "active_ingredients": tuple(
                value.strip()
                for value in medicine.active_ingredients
                if value and value.strip()
            ),
        }

    @staticmethod
    def review_fingerprint(medicine: Medicine) -> str:
        """Bind a displayed option to the exact reviewed package and safety facts."""
        snapshot = {
            field: getattr(medicine, field)
            for field in (
                "name",
                "manufacturer",
                "barcode",
                "spec",
                "category",
                "expire_date",
                "package_verified",
                "guidance_source",
                "tags",
                "aliases",
                "active_ingredients",
                "indications",
                "dosage",
                "contraindications",
                "structured_contraindications",
                "safety_note",
                "is_otc",
                "safety_review_status",
                "safety_reviewed_by",
                "safety_reviewed_at",
            )
        }
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _compact(value: object) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())

    @classmethod
    def _has_unnegated_term(cls, text: str, term: str) -> bool:
        for match in re.finditer(re.escape(term), str(text or ""), flags=re.IGNORECASE):
            prefix = str(text or "")[max(0, match.start() - 8):match.start()]
            clause = re.split(r"[，。；、,;!?！？]", prefix)[-1]
            if re.search(r"(?:没有|没|无|否认|未患|排除)\s*$", clause):
                continue
            return True
        return False

    @staticmethod
    def _allergy_terms(value: str) -> list[str]:
        terms: list[str] = []
        for raw in re.split(r"[\s,，、;；/：:]+", value.lower()):
            term = raw.strip("：:()（）[]【】")
            if re.search(r"(?:没有|并没有|没|无|否认).{0,6}(?:过敏|禁忌|不耐受)", term):
                continue
            for marker in (
                "药物过敏史", "过敏史", "不耐受史", "禁忌史",
                "药物过敏", "过敏", "禁忌", "不能使用", "不能用", "不耐受",
            ):
                term = term.replace(marker, "")
            term = re.sub(r"^(?:本次|既往资料|过敏|禁忌|我|本人|患者)?(?:曾经|曾|有|对|存在|明确)+", "", term)
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
