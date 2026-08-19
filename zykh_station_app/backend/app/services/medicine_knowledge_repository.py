from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from ..repositories.medicine_repository import (
    BUNDLED_LABEL_SAFETY_IDS,
    MedicineRepository,
)
from ..schemas.inquiry import CandidateMedicine, TreatmentMedicine, TreatmentOption
from ..schemas.medicine import Medicine
from .cabinet_v2_catalog import CabinetMappingError, cabinet_for_medicine_id
from .medicine_combination_policy import CombinationAuthorization
from .offline_inquiry_rules import OfflineInquiryRules, RULES


CHRONIC_CONDITION_TERMS_BY_CODE: dict[str, tuple[str, ...]] = {
    "diabetes": ("糖尿病", "高血糖", "血糖异常"),
    "renal_impairment": ("肾功能不全", "肾功能衰竭", "肾损害", "肾衰", "肾病"),
    "liver_impairment": ("肝功能不全", "肝功能受损", "肝损害", "肝病"),
    "cardiac_disease": ("严重心脏疾病", "严重心脏病", "严重心力衰竭"),
    "hypercalcemia": ("高钙血症",),
    "hyperphosphatemia": ("高磷血症",),
    "hypophosphatemia": ("低磷血症",),
    "myasthenia_gravis": ("重症肌无力",),
    "galactose_intolerance": ("半乳糖不耐受",),
    "intestinal_obstruction": ("肠梗阻",),
    "peptic_ulcer": ("消化道溃疡", "消化性溃疡", "胃溃疡"),
    "gastrointestinal_bleeding": ("胃肠道出血", "消化道出血", "胃出血"),
    "gastrointestinal_perforation": ("胃肠道穿孔", "消化道穿孔"),
    "hypotension": ("低血压",),
    "pregnancy": ("孕妇", "怀孕", "妊娠"),
    "breastfeeding": ("哺乳",),
    "asthma": ("哮喘",),
}
CHRONIC_CONDITION_GROUPS: tuple[tuple[str, ...], ...] = tuple(
    CHRONIC_CONDITION_TERMS_BY_CODE.values()
)
SINGLE_CHARACTER_NUTRIENT_TERMS = frozenset(
    {"钙", "磷", "钾", "氯", "镁", "铁", "铜", "锌", "锰", "碘", "铬", "钼", "硒", "镍", "硅", "锡", "钒"}
)
IBUPROFEN_CONCURRENT_ANALGESIC_TERMS = (
    "布洛芬",
    "芬必得",
    "阿司匹林",
    "萘普生",
    "双氯芬酸",
    "塞来昔布",
    "依托考昔",
    "吲哚美辛",
    "洛索洛芬",
    "酮洛芬",
    "对乙酰氨基酚",
)

# Retrieval-only equivalents bridge common spoken symptom wording to the
# reviewed terminology already stored in the medicine label fields. They do
# not make a treatment decision or bypass any availability/safety filter.
RETRIEVAL_TERM_EQUIVALENTS: tuple[tuple[str, str], ...] = (
    ("发烧", "发热"),
    ("发热", "退热"),
    ("头疼", "头痛"),
    ("喉咙疼", "咽痛"),
    ("喉咙痛", "咽痛"),
    ("嗓子疼", "咽痛"),
    ("嗓子痛", "咽痛"),
    ("咽喉疼", "咽痛"),
    ("咽喉痛", "咽痛"),
    ("喉咙疼", "咽喉不适"),
    ("喉咙痛", "咽喉不适"),
    ("嗓子疼", "咽喉不适"),
    ("嗓子痛", "咽喉不适"),
    ("咽喉疼", "咽喉不适"),
    ("咽喉痛", "咽喉不适"),
    ("拉肚子", "腹泻"),
    ("窜稀", "腹泻"),
    ("暑湿", "暑热"),
    ("清水样鼻涕", "清水鼻涕"),
    ("鼻涕像清水", "清水鼻涕"),
    ("流鼻水", "流涕"),
    ("打喷嚏", "连续打喷嚏"),
    ("肚子有点痛", "胃痛"),
    ("肚子痛", "胃痛"),
    ("肚子疼", "胃痛"),
    ("腹痛", "胃痛"),
    ("胃肠不适", "胃部不适"),
    ("舌头上打了个泡", "口腔起泡"),
    ("舌头上起泡", "口腔起泡"),
    ("舌头起泡", "口腔起泡"),
    ("脚扭了", "扭伤"),
    ("扭脚", "扭伤"),
    ("血压高", "血压管理"),
    ("高血压", "血压管理"),
    ("降压", "血压管理"),
)
RETRIEVAL_STOP_NGRAMS = frozenset(
    {
        "一般",
        "不适",
        "今天",
        "使用",
        "出现",
        "开始",
        "当前",
        "患者",
        "成人",
        "本次",
        "相关",
        "目前",
        "症状",
        "用于",
        "需要",
    }
)
CLINICIAN_GATED_RULE_KEYS = frozenset(
    {"influenza", "bacterial_respiratory", "bacterial_skin", "fungus"}
)
CLINICIAN_GATED_RETRIEVAL_IDS = frozenset(
    {
        medicine_id
        for rule in RULES
        if rule.key in CLINICIAN_GATED_RULE_KEYS
        for medicine_id in (*rule.medicine_ids, *rule.alternative_ids)
    }
    - {
        medicine_id
        for rule in RULES
        if rule.key not in CLINICIAN_GATED_RULE_KEYS
        for medicine_id in (*rule.medicine_ids, *rule.alternative_ids)
    }
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
            blocked = False
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
                blocked = True
            if (
                (not used_reference or bool(context.allergy_text.strip()))
                and self.has_allergy_conflict(medicine, allergy_context)
            ):
                notices.append(
                    MedicineSafetyNotice(
                        code="allergy_conflict",
                        message=f"根据已记录的过敏或禁忌信息，本次未推荐“{medicine.name}”。",
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                    )
                )
                blocked = True
            if (
                (not used_reference or bool(context.history_text.strip()))
                and self.has_chronic_condition_conflict(medicine, history_context)
            ):
                notices.append(
                    MedicineSafetyNotice(
                        code="history_contraindication",
                        message=f"根据已记录的病史与药品禁忌，本次未推荐“{medicine.name}”。",
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                    )
                )
                blocked = True
            if blocked:
                continue
            if len(candidates) < limit:
                candidates.append(candidate)
        return CandidatePoolAssessment(candidates=candidates, notices=notices)

    @classmethod
    def _candidate_from_medicine(cls, medicine: Medicine) -> CandidateMedicine:
        facts = cls._safety_facts(medicine)
        try:
            cabinet = cabinet_for_medicine_id(medicine.id)
        except CabinetMappingError:
            cabinet = None
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
            cabinet_id=cabinet.id if cabinet else None,
            cabinet_label=cabinet.label if cabinet else "",
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
        *,
        combination_authorization: CombinationAuthorization | None = None,
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
            if len(normalized_ids) > 1:
                combination_id = str(raw.get("combination_id") or "").strip()
                authorization_fingerprint = str(
                    raw.get("authorization_fingerprint") or ""
                ).strip()
                decision = (
                    combination_authorization.validate_and_expand(combination_id)
                    if combination_authorization is not None and combination_id
                    else None
                )
                expected_ids = (
                    [medicine.id for medicine in decision.medicines]
                    if decision is not None and decision.allowed
                    else []
                )
                if (
                    len(set(normalized_ids)) != len(normalized_ids)
                    or any(medicine_id not in allowed for medicine_id in normalized_ids)
                    or decision is None
                    or not decision.allowed
                    or normalized_ids != expected_ids
                    or not authorization_fingerprint
                    or authorization_fingerprint != decision.authorization_fingerprint
                ):
                    notices.append(
                        MedicineSafetyNotice(
                            code="combination_not_approved",
                            message="该多药方案未命中当前病例的受控组合，本次未被采用。",
                        )
                    )
                    continue
                accepted_payloads.append(
                    {
                        **raw,
                        "combination_id": decision.combination_id,
                        "authorization_fingerprint": decision.authorization_fingerprint,
                        "medicine_ids": expected_ids,
                        "usage_by_medicine": dict(
                            decision.reviewed_usage_by_medicine
                        ),
                    }
                )
                continue

            if (
                normalized_ids[0] not in allowed
                or str(raw.get("combination_id") or "").strip()
                or str(raw.get("authorization_fingerprint") or "").strip()
            ):
                continue
            accepted_payloads.append(raw)
        return MedicineSelectionAssessment(
            options=self._options_from_model_payload(
                {"options": accepted_payloads},
                safe_pool,
            ),
            notices=notices,
        )

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
                    combination_id=str(raw.get("combination_id") or "").strip(),
                    combination_authorization_fingerprint=str(
                        raw.get("authorization_fingerprint") or ""
                    ).strip(),
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
                            recommended_usage=(
                                self._clean_option_text(
                                    usage_by_medicine.get(candidate.id),
                                    candidate.dosage,
                                    120,
                                )
                                if str(raw.get("combination_id") or "").strip()
                                else self._safe_recommended_usage(
                                    usage_by_medicine.get(candidate.id),
                                    candidate.dosage,
                                )
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
        raw_query = str(case_text or "").lower()
        expanded_terms = [
            reviewed_term
            for spoken_term, reviewed_term in RETRIEVAL_TERM_EQUIVALENTS
            if cls._has_unnegated_retrieval_term(raw_query, spoken_term)
        ]
        query = "；".join((raw_query, *expanded_terms))
        controlled_ids = cls._controlled_retrieval_ids(query)
        query_ngrams = cls._text_ngrams(query)
        if not query_ngrams and not controlled_ids:
            return []
        scored: list[tuple[int, int, CandidateMedicine]] = []
        for index, candidate in enumerate(candidates):
            if (
                candidate.id in CLINICIAN_GATED_RETRIEVAL_IDS
                and candidate.id not in controlled_ids
            ):
                continue
            fields = [
                candidate.name,
                candidate.category,
                candidate.indications,
                *candidate.tags,
                *candidate.aliases,
            ]
            document = " ".join(fields).lower()
            overlap = len(query_ngrams & cls._text_ngrams(document))
            direct = sum(
                4
                for term in (
                    candidate.name,
                    candidate.category,
                    *candidate.tags,
                    *candidate.aliases,
                )
                if (
                    len(term.strip()) >= 2
                    and cls._has_unnegated_retrieval_term(
                        query,
                        term.strip().lower(),
                    )
                )
            )
            if (
                candidate.id in BUNDLED_LABEL_SAFETY_IDS
                and candidate.id not in controlled_ids
                and not direct
            ):
                continue
            controlled = 16 if candidate.id in controlled_ids else 0
            if controlled or direct or overlap >= 2:
                scored.append((overlap + direct + controlled, -index, candidate))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not scored:
            return []
        return [item[2] for item in scored[:limit]]

    @classmethod
    def _controlled_retrieval_ids(cls, query: str) -> set[str]:
        """Map reviewed spoken symptom rules to retrieval IDs only.

        ``_available`` and the later safety/ranking stages still decide whether
        any mapped item can be shown or used.
        """
        matched_ids: set[str] = set()
        disease_terms = ("感冒", "上呼吸道感染")
        disease_referenced = any(term in query for term in disease_terms)
        disease_affirmed = any(
            cls._has_active_disease_reference(query, term)
            for term in disease_terms
        )
        for rule in RULES:
            if rule.key == "cold" and disease_referenced and not disease_affirmed:
                continue
            concept = rule.concept.strip().lower()
            matched = bool(
                concept
                and cls._has_unnegated_retrieval_term(query, concept)
            ) or any(
                cls._has_unnegated_retrieval_term(query, term)
                for term in rule.terms
            )
            if not matched:
                continue
            primary_ids, alternative_ids = OfflineInquiryRules._conditional_medicine_ids(
                rule,
                query,
            )
            matched_ids.update((*primary_ids, *alternative_ids))
        respiratory_terms = ("咳嗽", "干咳", "咳痰", "鼻塞", "流涕", "流鼻涕")
        chill_terms = ("发冷", "怕冷", "寒战")
        same_clause_cluster = any(
            not cls._cold_cluster_explicitly_disclaimed(clause)
            and any(
                cls._has_active_retrieval_term(clause, term)
                for term in respiratory_terms
            )
            and any(
                cls._has_active_retrieval_term(clause, term)
                for term in chill_terms
            )
            for clause in re.split(r"[。；;！!？，,]", query)
            if clause.strip()
        )
        if same_clause_cluster and (not disease_referenced or disease_affirmed):
            # Retrieval-only symptom cluster: the combination expands the
            # reviewed cold-use candidate, while either symptom alone does not
            # infer a diagnosis or bypass later eligibility/safety checks.
            # Explicit rejection of a cold diagnosis, symptoms attributed to
            # separate causes, and already-resolved respiratory symptoms do
            # not satisfy this cluster.
            matched_ids.add("slot-01-fufang-ganmaoling")
        return matched_ids

    @classmethod
    def _has_active_disease_reference(cls, text: str, term: str) -> bool:
        source = str(text or "")
        for match in re.finditer(re.escape(term), source, flags=re.IGNORECASE):
            if cls._retrieval_match_is_negated(source, match.start()):
                continue
            suffix = source[match.end():match.end() + 14]
            if re.match(
                r"(?:已经|已)?(?:明显)?"
                r"(?:好(?:了)?|缓解(?:了)?|消失(?:了)?|恢复(?:了)?|痊愈(?:了)?)",
                suffix,
            ):
                continue
            return True
        return False

    @staticmethod
    def _cold_cluster_explicitly_disclaimed(text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        if re.search(
            r"(?:不是|并非|没有|未|不)(?:在)?(?:同时|一起|同一时间)",
            compact,
        ):
            return True
        if re.search(r"(?:分别|不同时间|先后)(?:发生|出现)?", compact):
            return True
        return bool(
            re.search(
                r"(?:是|由|由于|因为).{0,10}"
                r"(?:过敏|低血糖|疫苗|空调|寒冷)(?:导致|引起)?",
                compact,
            )
        )

    @classmethod
    def _has_active_retrieval_term(cls, text: str, term: str) -> bool:
        if not cls._has_unnegated_retrieval_term(text, term):
            return False
        resolved = re.search(
            rf"{re.escape(term)}(?:已经|已)?(?:明显)?"
            r"(?:好(?:了)?|缓解(?:了)?|消失(?:了)?|恢复(?:了)?)",
            str(text or ""),
            flags=re.IGNORECASE,
        )
        return resolved is None

    @staticmethod
    def _has_unnegated_retrieval_term(text: str, term: str) -> bool:
        source = str(text or "")
        matches = list(re.finditer(re.escape(term), source, flags=re.IGNORECASE))
        if not matches:
            return False
        for match in matches:
            if not MedicineKnowledgeRepository._retrieval_match_is_negated(
                source,
                match.start(),
            ):
                return True
        return False

    @staticmethod
    def _retrieval_match_is_negated(text: str, start: int) -> bool:
        clause_start = max(
            str(text or "").rfind(separator, 0, start)
            for separator in ("。", "；", ";", "！", "？")
        )
        prefix = str(text or "")[clause_start + 1:start]
        if re.search(
            r"(?:无法|不能|未能|尚未|难以|不)(?:完全)?排除(?:是|为)?$",
            prefix,
        ):
            return False
        direct = re.search(
            r"(?:(?:没有|并没有|没|无(?!法)|否认|不是|并非|非(?!常)|并不|"
            r"(?:(?:已经|已|明确)?排除))"
            r"(?:明显|什么|任何|一点|怎么)?[^。；;，,但是不过却]{0,14}|"
            r"不(?:明显|怎么)?(?:是)?)$",
            prefix,
        )
        if direct is None:
            return False
        negation_start = direct.start()
        return not bool(
            re.search(r"(?:但是|但|不过|却|现在|目前)", prefix[negation_start:])
        )

    @staticmethod
    def _text_ngrams(value: str) -> set[str]:
        chunks = re.findall(r"[a-z]+|[\u4e00-\u9fff]+", str(value or "").lower())
        return {
            chunk[index:index + 2]
            for chunk in chunks
            for index in range(max(0, len(chunk) - 1))
            if (
                len(chunk[index:index + 2]) == 2
                and chunk[index:index + 2] not in RETRIEVAL_STOP_NGRAMS
            )
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
        if "布洛芬" in facts["active_ingredients"]:
            concurrent = next(
                (
                    term
                    for term in IBUPROFEN_CONCURRENT_ANALGESIC_TERMS
                    if cls._compact(term) in used_text
                ),
                "",
            )
            if concurrent:
                return concurrent
        references = (*facts["active_ingredients"], *facts["aliases"], medicine.name)
        return next(
            (
                value
                for value in references
                if (
                    len(cls._compact(value)) >= 2
                    or cls._compact(value) in SINGLE_CHARACTER_NUTRIENT_TERMS
                )
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
        return MedicineRepository.review_fingerprint(medicine)

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
