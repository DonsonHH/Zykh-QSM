from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Protocol, Sequence

from ..schemas.inquiry import CandidateMedicine
from ..schemas.medicine import (
    MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION,
    ApprovedMedicineCombination,
    MedicineIngredientConflictRule,
)


CLINICAL_POLICY_VERSION = MEDICINE_COMBINATION_CLINICAL_POLICY_VERSION
ALLOWED_RISK_LEVELS = frozenset({"low", "medium"})


GROUNDING_PATTERNS: dict[str, tuple[str, ...]] = {
    "acute_watery_diarrhea": (
        "水样腹泻",
        "水样便",
        "稀水样便",
        "急性水样腹泻",
    ),
    "oral_intake_tolerated": (
        "能喝水",
        "可以喝水",
        "喝得下水",
        "可以饮水",
        "能够饮水",
        "能进食",
        "可以进食",
        "吃得下",
    ),
    "superficial_wound": (
        "浅表伤口",
        "浅表创面",
        "擦伤",
        "小伤口",
        "轻微割伤",
        "伤口不深",
        "刀伤不深",
    ),
    "bleeding_controlled": (
        "已经止血",
        "已止血",
        "出血已经止住",
        "出血已止住",
        "出血已控制",
        "不再出血",
    ),
    "small_dry_wound": (
        "小而浅",
        "伤口很小",
        "干燥伤口",
        "伤口干燥",
        "渗液少",
    ),
    "needs_gauze_cover": (
        "需要纱布",
        "需用纱布",
        "需要敷料",
        "需敷料",
        "渗液较多",
    ),
    "bloody_stool": ("便血", "大便带血", "血便"),
    "black_stool": ("黑便", "柏油样便"),
    "persistent_high_fever": ("持续高热", "高烧不退", "高热不退"),
    "severe_abdominal_pain": ("剧烈腹痛", "腹痛剧烈", "严重腹痛"),
    "significant_dehydration": (
        "明显脱水",
        "严重脱水",
        "尿量明显减少",
    ),
    "persistent_vomiting": ("持续呕吐", "反复呕吐", "一直吐"),
    "deep_wound": ("深部伤口", "伤口很深", "深伤口", "深部创面"),
    "animal_bite": ("动物咬伤", "猫咬", "狗咬", "犬咬", "抓咬伤"),
    "continued_bleeding": ("持续出血", "还在出血", "止不住血", "出血不止"),
    "wound_infection": ("伤口感染", "化脓", "红肿热痛", "脓液"),
    "embedded_foreign_body": ("异物残留", "异物嵌入", "玻璃碎片"),
}


class CombinationPolicyRepository(Protocol):
    def list_case_reviewed_combinations(self) -> list[ApprovedMedicineCombination]: ...

    def list_reviewed_ingredient_conflicts(
        self,
    ) -> list[MedicineIngredientConflictRule]: ...


@dataclass(frozen=True)
class CombinationClinicalContext:
    present_facts: frozenset[str] = field(default_factory=frozenset)
    absent_facts: frozenset[str] = field(default_factory=frozenset)
    risk_level: str = ""
    age_years: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "present_facts",
            frozenset(_normalize_code(value) for value in self.present_facts if _normalize_code(value)),
        )
        object.__setattr__(
            self,
            "absent_facts",
            frozenset(_normalize_code(value) for value in self.absent_facts if _normalize_code(value)),
        )
        object.__setattr__(self, "risk_level", _normalize_code(self.risk_level))


@dataclass(frozen=True)
class AllowedMedicineCombination:
    combination_id: str
    label: str
    medicine_ids: tuple[str, ...]
    reviewed_usage_by_medicine: dict[str, str]
    authorization_fingerprint: str


@dataclass(frozen=True)
class CombinationSelectionDecision:
    allowed: bool
    code: str
    combination_id: str
    medicines: tuple[CandidateMedicine, ...] = ()
    reviewed_usage_by_medicine: dict[str, str] = field(default_factory=dict)
    authorization_fingerprint: str = ""


class CombinationAuthorization:
    """One immutable allow-list shared by model input and backend validation."""

    def __init__(
        self,
        allowed_combinations: Sequence[AllowedMedicineCombination],
        safe_by_id: dict[str, CandidateMedicine],
    ) -> None:
        self.allowed_combinations = tuple(allowed_combinations)
        self._allowed_by_id = {
            combination.combination_id: combination
            for combination in self.allowed_combinations
        }
        self._safe_by_id = dict(safe_by_id)

    def model_payload(self) -> list[dict[str, object]]:
        return [
            {
                "combination_id": combination.combination_id,
                "label": combination.label,
                "medicine_ids": list(combination.medicine_ids),
                "reviewed_usage_by_medicine": dict(
                    combination.reviewed_usage_by_medicine
                ),
                "authorization_fingerprint": combination.authorization_fingerprint,
            }
            for combination in self.allowed_combinations
        ]

    def validate_and_expand(self, combination_id: str) -> CombinationSelectionDecision:
        normalized_id = str(combination_id or "").strip()
        combination = self._allowed_by_id.get(normalized_id)
        if combination is None:
            return CombinationSelectionDecision(
                allowed=False,
                code="combination_not_authorized",
                combination_id=normalized_id,
            )
        medicines = tuple(
            self._safe_by_id[medicine_id] for medicine_id in combination.medicine_ids
        )
        return CombinationSelectionDecision(
            allowed=True,
            code="authorized",
            combination_id=combination.combination_id,
            medicines=medicines,
            reviewed_usage_by_medicine=dict(
                combination.reviewed_usage_by_medicine
            ),
            authorization_fingerprint=combination.authorization_fingerprint,
        )

    def restricted_to(self, combination_ids: Sequence[str]) -> "CombinationAuthorization":
        allowed_ids = {str(value or "").strip() for value in combination_ids}
        return CombinationAuthorization(
            [
                combination
                for combination in self.allowed_combinations
                if combination.combination_id in allowed_ids
            ],
            self._safe_by_id,
        )


class MedicineCombinationPolicy:
    def __init__(self, repository: CombinationPolicyRepository) -> None:
        self.repository = repository

    def authorize(
        self,
        context: CombinationClinicalContext,
        safe_pool: Sequence[CandidateMedicine],
    ) -> CombinationAuthorization:
        safe_by_id = self._unambiguous_safe_pool(safe_pool)
        if not self._valid_context(context):
            return CombinationAuthorization((), safe_by_id)
        conflict_pairs = self._reviewed_conflict_pairs()
        combinations = getattr(
            self.repository,
            "list_case_reviewed_combinations",
            None,
        )
        if not callable(combinations):
            return CombinationAuthorization((), safe_by_id)

        allowed: list[AllowedMedicineCombination] = []
        for combination in sorted(combinations(), key=lambda item: item.combination_id):
            if not self._complete_review_contract(combination):
                continue
            if not self._context_matches(combination, context):
                continue
            if not self._members_match(
                combination,
                safe_by_id,
                conflict_pairs,
            ):
                continue
            allowed.append(
                AllowedMedicineCombination(
                    combination_id=combination.combination_id,
                    label=combination.label,
                    medicine_ids=tuple(combination.medicine_ids),
                    reviewed_usage_by_medicine=dict(
                        combination.reviewed_usage_by_medicine
                    ),
                    authorization_fingerprint=self._authorization_fingerprint(
                        combination,
                        context,
                    ),
                )
            )
        return CombinationAuthorization(allowed, safe_by_id)

    @staticmethod
    def _unambiguous_safe_pool(
        safe_pool: Sequence[CandidateMedicine],
    ) -> dict[str, CandidateMedicine]:
        counts = Counter(str(candidate.id).strip() for candidate in safe_pool)
        return {
            candidate.id: candidate
            for candidate in safe_pool
            if candidate.id and counts[candidate.id] == 1
        }

    @staticmethod
    def _valid_context(context: CombinationClinicalContext) -> bool:
        return (
            context.risk_level in ALLOWED_RISK_LEVELS
            and not (context.present_facts & context.absent_facts)
            and (context.age_years is None or 0 <= context.age_years <= 130)
        )

    @staticmethod
    def _complete_review_contract(
        combination: ApprovedMedicineCombination,
    ) -> bool:
        medicine_ids = combination.medicine_ids
        applicability = combination.applicability
        allowed_risks = {_normalize_code(value) for value in applicability.allowed_risk_levels}
        member_facts = applicability.member_required_any_facts
        evidence_complete = bool(combination.evidence_refs) and all(
            evidence.source_title.strip()
            and evidence.source_url.strip()
            and evidence.supports.strip()
            for evidence in combination.evidence_refs
        )
        return (
            combination.review_status == "reviewed"
            and bool(combination.reviewed_by.strip())
            and bool(combination.reviewed_at.strip())
            and combination.clinical_policy_version == CLINICAL_POLICY_VERSION
            and 2 <= len(medicine_ids) <= 4
            and len(set(medicine_ids)) == len(medicine_ids)
            and set(combination.member_identity_fingerprints) == set(medicine_ids)
            and all(
                str(combination.member_identity_fingerprints[item]).strip()
                for item in medicine_ids
            )
            and set(combination.member_review_fingerprints) == set(medicine_ids)
            and all(
                str(combination.member_review_fingerprints[item]).strip()
                for item in medicine_ids
            )
            and set(combination.reviewed_usage_by_medicine) == set(medicine_ids)
            and all(
                str(combination.reviewed_usage_by_medicine[item]).strip()
                for item in medicine_ids
            )
            and set(member_facts) == set(medicine_ids)
            and all(
                any(_normalize_code(value) for value in member_facts[item])
                for item in medicine_ids
            )
            and bool(allowed_risks)
            and allowed_risks <= ALLOWED_RISK_LEVELS
            and (
                applicability.min_age_years is None
                or applicability.max_age_years is None
                or applicability.min_age_years <= applicability.max_age_years
            )
            and evidence_complete
            and bool(combination.provenance.strip())
            and bool(combination.review_note.strip())
        )

    @staticmethod
    def _context_matches(
        combination: ApprovedMedicineCombination,
        context: CombinationClinicalContext,
    ) -> bool:
        rule = combination.applicability
        required_all = {_normalize_code(value) for value in rule.required_all_facts}
        required_any = {
            _normalize_code(value) for value in rule.required_any_facts if _normalize_code(value)
        }
        must_be_absent = {
            _normalize_code(value)
            for value in rule.must_be_absent_facts
            if _normalize_code(value)
        }
        allowed_risks = {
            _normalize_code(value) for value in rule.allowed_risk_levels if _normalize_code(value)
        }
        if not required_all <= context.present_facts:
            return False
        if required_any and not (required_any & context.present_facts):
            return False
        # Unknown red-flag status is not equivalent to an explicit negative.
        if not must_be_absent <= context.absent_facts:
            return False
        if must_be_absent & context.present_facts:
            return False
        if context.risk_level not in allowed_risks:
            return False
        if rule.min_age_years is not None and (
            context.age_years is None or context.age_years < rule.min_age_years
        ):
            return False
        if rule.max_age_years is not None and (
            context.age_years is None or context.age_years > rule.max_age_years
        ):
            return False
        return all(
            bool(
                {
                    _normalize_code(value)
                    for value in facts
                    if _normalize_code(value)
                }
                & context.present_facts
            )
            for facts in rule.member_required_any_facts.values()
        )

    @staticmethod
    def _members_match(
        combination: ApprovedMedicineCombination,
        safe_by_id: dict[str, CandidateMedicine],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        if any(medicine_id not in safe_by_id for medicine_id in combination.medicine_ids):
            return False
        members = [safe_by_id[medicine_id] for medicine_id in combination.medicine_ids]
        if any(member.stock <= 0 or not member.review_fingerprint for member in members):
            return False
        if any(
            member.review_fingerprint
            != combination.member_review_fingerprints.get(member.id)
            for member in members
        ):
            return False

        seen_ingredients: set[str] = set()
        for member in members:
            ingredients = {
                _normalize_ingredient(ingredient)
                for ingredient in member.active_ingredients
                if _normalize_ingredient(ingredient)
            }
            if ingredients & seen_ingredients:
                return False
            if any(
                tuple(sorted((left, right))) in conflict_pairs
                for left in seen_ingredients
                for right in ingredients
            ):
                return False
            seen_ingredients.update(ingredients)
        return True

    def _reviewed_conflict_pairs(self) -> frozenset[tuple[str, str]]:
        list_rules = getattr(
            self.repository,
            "list_reviewed_ingredient_conflicts",
            None,
        )
        if not callable(list_rules):
            return frozenset()
        pairs: set[tuple[str, str]] = set()
        for rule in list_rules():
            if str(rule.disposition).strip().lower() != "block":
                continue
            left = _normalize_ingredient(rule.left_ingredient)
            right = _normalize_ingredient(rule.right_ingredient)
            if left and right and left != right:
                pairs.add(tuple(sorted((left, right))))
        return frozenset(pairs)

    @staticmethod
    def _authorization_fingerprint(
        combination: ApprovedMedicineCombination,
        context: CombinationClinicalContext,
    ) -> str:
        snapshot = {
            "combination_id": combination.combination_id,
            "clinical_policy_version": combination.clinical_policy_version,
            "medicine_ids": combination.medicine_ids,
            "member_review_fingerprints": combination.member_review_fingerprints,
            "reviewed_usage_by_medicine": combination.reviewed_usage_by_medicine,
            "present_facts": sorted(context.present_facts),
            "absent_facts": sorted(context.absent_facts),
            "risk_level": context.risk_level,
            "age_years": context.age_years,
        }
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _normalize_code(value: object) -> str:
    return re.sub(r"[^0-9a-z_]+", "_", str(value or "").strip().lower()).strip("_")


def _normalize_ingredient(value: object) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def combination_context_from_observations(
    observations: Sequence[object],
    *,
    risk_level: str,
    age_years: int | None,
) -> CombinationClinicalContext:
    """Translate only grounded present/absent observations into policy facts.

    The model's case summary and possible diagnosis are intentionally excluded.
    An uncertain or missing red flag never becomes an explicit negative.
    """

    present: set[str] = set()
    absent: set[str] = set()
    for observation in observations:
        if isinstance(observation, dict):
            status = str(observation.get("status") or "").strip().lower()
            concept = str(observation.get("concept") or "")
            evidence = str(observation.get("evidence") or "")
        else:
            status = str(getattr(observation, "status", "") or "").strip().lower()
            concept = str(getattr(observation, "concept", "") or "")
            evidence = str(getattr(observation, "evidence", "") or "")
        if status not in {"present", "absent"}:
            continue
        grounded_text = re.sub(r"\s+", "", f"{concept}；{evidence}").lower()
        matched = {
            fact
            for fact, patterns in GROUNDING_PATTERNS.items()
            if any(re.sub(r"\s+", "", pattern).lower() in grounded_text for pattern in patterns)
        }
        if status == "present":
            present.update(matched)
        else:
            absent.update(matched)
    return CombinationClinicalContext(
        present_facts=frozenset(present),
        absent_facts=frozenset(absent),
        risk_level=risk_level,
        age_years=age_years,
    )
