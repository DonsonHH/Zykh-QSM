from __future__ import annotations

from datetime import date
import re

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.inquiry import CandidateMedicine, TreatmentMedicine, TreatmentOption
from ..schemas.medicine import Medicine


# Inquiry safety facts are deliberately keyed by the fixed cabinet identity.
# They complement, but never replace, the live stock/package/label rows read
# from MedicineRepository on every decision.
MEDICINE_SAFETY_FACTS: dict[str, dict[str, tuple[str, ...]]] = {
    "slot-01-fufang-ganmaoling": {
        "aliases": ("复方感冒灵", "999感冒灵"),
        "active_ingredients": ("对乙酰氨基酚",),
    },
    "slot-02-centrum": {"aliases": ("善存", "多维元素"), "active_ingredients": ()},
    "slot-03-diosmectite": {
        "aliases": ("思密达", "蒙脱石"),
        "active_ingredients": ("蒙脱石",),
    },
    "slot-04-amoxicillin": {"aliases": ("阿莫西林",), "active_ingredients": ("阿莫西林",)},
    "slot-05-nin-jiom-pei-pa-koa": {
        "aliases": ("京都念慈庵", "川贝枇杷膏", "枇杷膏"),
        "active_ingredients": (),
    },
    "slot-06-lactulose": {"aliases": ("乳果糖",), "active_ingredients": ("乳果糖",)},
    "slot-07-yinhuang": {"aliases": ("银黄", "银黄颗粒"), "active_ingredients": ()},
    "slot-08-huoxiang-zhengqi": {"aliases": ("藿香正气",), "active_ingredients": ()},
    "slot-09-bifid-triple": {"aliases": ("贝飞达", "双歧杆菌三联活菌"), "active_ingredients": ()},
    "slot-10-gauze": {"aliases": ("医用纱布", "纱布"), "active_ingredients": ()},
    "slot-11-guilin-xiguashuang": {"aliases": ("桂林西瓜霜", "西瓜霜"), "active_ingredients": ()},
    "slot-12-hydrotalcite": {"aliases": ("铝碳酸镁",), "active_ingredients": ("铝碳酸镁",)},
    "slot-13-ibuprofen": {
        "aliases": ("芬必得", "布洛芬"),
        "active_ingredients": ("布洛芬",),
    },
    "slot-14-oseltamivir": {
        "aliases": ("奥司他韦", "磷酸奥司他韦"),
        "active_ingredients": ("奥司他韦",),
    },
    "slot-15-mupirocin": {"aliases": ("莫匹罗星",), "active_ingredients": ("莫匹罗星",)},
    "slot-16-ketoconazole": {"aliases": ("酮康唑",), "active_ingredients": ("酮康唑",)},
    "slot-17-iodophor": {"aliases": ("碘伏", "聚维酮碘"), "active_ingredients": ("聚维酮碘",)},
    "slot-18-budesonide-nasal": {"aliases": ("雷诺考特", "布地奈德"), "active_ingredients": ("布地奈德",)},
    "slot-19-ketoprofen-gel": {"aliases": ("法斯通", "酮洛芬"), "active_ingredients": ("酮洛芬",)},
    "slot-20-bandage": {"aliases": ("创口贴",), "active_ingredients": ()},
    "slot-21-amlodipine": {"aliases": ("氨氯地平",), "active_ingredients": ("氨氯地平",)},
    "slot-22-cotton-swab": {"aliases": ("医用棉签", "棉签"), "active_ingredients": ()},
    "slot-23-desloratadine": {"aliases": ("枸地氯雷他定",), "active_ingredients": ("枸地氯雷他定",)},
}


CHRONIC_CONDITION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("糖尿病", "高血糖", "血糖异常"),
    ("肾功能不全", "肾功能衰竭", "肾损害", "肾衰", "肾病"),
    ("肝功能不全", "肝功能受损", "肝损害", "肝病"),
    ("高钙血症",),
    ("高磷血症",),
    ("低磷血症",),
    ("重症肌无力",),
    ("半乳糖不耐受",),
    ("肠梗阻",),
    ("消化道溃疡", "胃溃疡"),
    ("低血压",),
    ("孕妇", "怀孕", "妊娠"),
    ("哺乳",),
    ("哮喘",),
)


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
            facts = self._safety_facts(medicine)
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
                    tags=medicine.tags,
                    contraindications=medicine.contraindications,
                    aliases=list(facts["aliases"]),
                    active_ingredients=list(facts["active_ingredients"]),
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
        has_existing_direction = medicine.id in (directed_ids or set())
        if medicine.stock <= 0:
            return False
        if not medicine.package_verified:
            return False
        if (not medicine.is_otc or medicine.category == "慢病常用") and not has_existing_direction:
            return False
        if MedicineKnowledgeRepository.is_expired(medicine.expire_date):
            return False
        if MedicineKnowledgeRepository._used_medicine_conflict(medicine, context_text):
            return False
        if MedicineKnowledgeRepository.has_chronic_condition_conflict(medicine, context_text):
            return False
        return not MedicineKnowledgeRepository.has_allergy_conflict(medicine, context_text)

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
        warnings = cls._compact(" ".join(medicine.contraindications))
        return any(
            any(cls._has_unnegated_term(context_text, term) for term in group)
            and any(cls._compact(term) in warnings for term in group)
            for group in CHRONIC_CONDITION_GROUPS
        )

    @classmethod
    def _used_medicine_conflict(cls, medicine: Medicine, context_text: str) -> bool:
        matches = re.findall(
            r"(?:本次)?已用药\s*[：:]\s*([^；;\n]+)",
            str(context_text or ""),
            flags=re.IGNORECASE,
        )
        if not matches:
            return False
        used_text = cls._compact(" ".join(matches))
        if not used_text or used_text in {"无", "没有", "未使用", "还没有"}:
            return False
        facts = cls._safety_facts(medicine)
        references = (medicine.name, *facts["aliases"], *facts["active_ingredients"])
        return any(
            len(compact) >= 2 and compact in used_text
            for value in references
            if (compact := cls._compact(value))
        )

    @staticmethod
    def _safety_facts(medicine: Medicine) -> dict[str, tuple[str, ...]]:
        facts = MEDICINE_SAFETY_FACTS.get(medicine.id, {})
        aliases = tuple(
            dict.fromkeys(
                value.strip()
                for value in (medicine.name, *facts.get("aliases", ()))
                if value and value.strip()
            )
        )
        return {
            "aliases": aliases,
            "active_ingredients": tuple(facts.get("active_ingredients", ())),
        }

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
