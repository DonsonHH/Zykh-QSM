from __future__ import annotations

from dataclasses import dataclass

from ..repositories.medicine_repository import MedicineRepository
from ..schemas.inquiry import CandidateMedicine, InquiryEvaluateRequest, RiskLevel
from ..schemas.medicine import Medicine


@dataclass(frozen=True)
class RuleEvaluation:
    risk_level: RiskLevel
    risk_label: str
    symptoms_summary: str
    suggested_categories: list[str]
    candidate_medicines: list[CandidateMedicine]
    contraindication_warnings: list[str]
    safety_notice: str
    next_steps: list[str]
    can_proceed_to_dispense: bool


EMERGENCY_KEYWORDS = [
    "胸痛",
    "呼吸困难",
    "意识不清",
    "昏迷",
    "抽搐",
    "严重过敏",
    "喉头水肿",
    "大出血",
    "疑似中风",
    "口角歪斜",
    "肢体无力",
]

HIGH_KEYWORDS = ["高热不退", "严重外伤", "剧烈疼痛", "持续胸闷", "黑便", "呕血"]

MEDIUM_KEYWORDS = [
    "发热持续",
    "持续发热",
    "腹泻超过一天",
    "超过一天",
    "两天",
    "2天",
    "三天",
    "3天",
    "头晕",
    "老人",
    "老年",
    "孕",
    "症状不明确",
    "说不清",
]

CATEGORY_RULES = [
    (("咳嗽", "流涕", "鼻塞", "感冒", "咽痛"), ["感冒发热"]),
    (("头痛", "发热", "疼痛", "低热"), ["感冒发热", "解热镇痛"]),
    (("腹泻", "胃痛", "肚子痛", "腹痛", "呕吐"), ["肠胃"]),
    (("过敏", "瘙痒", "皮疹", "鼻炎"), ["过敏"]),
    (("擦伤", "破皮", "划伤", "小伤口"), ["外伤消毒"]),
    (("血压", "慢病", "长期用药", "心脑血管"), ["家庭常用"]),
]

CONTRAINDICATION_RULES = {
    "青霉素": "已填写青霉素相关过敏或禁忌，请避免相关药品并联系专业人员核验。",
    "布洛芬": "已填写布洛芬相关过敏或禁忌，候选药品已排除相关冲突项。",
    "阿司匹林": "已填写阿司匹林相关过敏或禁忌，候选药品已排除相关冲突项。",
    "碘": "已填写碘相关过敏或禁忌，外伤消毒用品需现场人员核验。",
}

MEDICINE_CONFLICT_KEYWORDS = {
    "布洛芬": ["布洛芬"],
    "阿司匹林": ["阿司匹林"],
    "碘": ["碘伏"],
}


class RulesEngine:
    def __init__(self, medicine_repository: MedicineRepository | None = None) -> None:
        self.medicine_repository = medicine_repository or MedicineRepository()

    def evaluate(self, request: InquiryEvaluateRequest) -> RuleEvaluation:
        risk_text = self._joined_text(request)
        category_text = self._category_text(request)
        categories = self._match_categories(category_text)
        warnings = self._contraindication_warnings(request.allergy_or_contraindication)
        risk_level = self._risk_level(risk_text, request)
        risk_label = self._risk_label(risk_level)
        medicines = self._candidate_medicines(categories, request.allergy_or_contraindication)
        has_stock = any(medicine.stock > 0 for medicine in medicines)
        can_proceed = risk_level == "low" and not warnings and has_stock
        if "家庭常用" in categories:
            can_proceed = False

        return RuleEvaluation(
            risk_level=risk_level,
            risk_label=risk_label,
            symptoms_summary=self._summary(request),
            suggested_categories=categories,
            candidate_medicines=[self._to_candidate(medicine) for medicine in medicines],
            contraindication_warnings=warnings,
            safety_notice=self._safety_notice(risk_level, can_proceed, categories),
            next_steps=self._next_steps(risk_level, can_proceed, categories),
            can_proceed_to_dispense=can_proceed,
        )

    def _joined_text(self, request: InquiryEvaluateRequest) -> str:
        return " ".join(
            [
                request.symptoms_text,
                request.duration,
                request.used_medicines,
                request.allergy_or_contraindication,
                request.scene_type,
            ]
        ).lower()

    def _category_text(self, request: InquiryEvaluateRequest) -> str:
        return " ".join([request.symptoms_text, request.duration]).lower()

    def _match_categories(self, text: str) -> list[str]:
        categories: list[str] = []
        for keywords, matched_categories in CATEGORY_RULES:
            if any(keyword in text for keyword in keywords):
                for category in matched_categories:
                    if category not in categories:
                        categories.append(category)
        if not categories:
            categories.append("感冒发热")
        return categories

    def _contraindication_warnings(self, allergy_text: str) -> list[str]:
        return [warning for keyword, warning in CONTRAINDICATION_RULES.items() if keyword in allergy_text]

    def _risk_level(self, text: str, request: InquiryEvaluateRequest) -> RiskLevel:
        if any(keyword in text for keyword in EMERGENCY_KEYWORDS):
            return "emergency"
        if any(keyword in text for keyword in HIGH_KEYWORDS):
            return "high"
        if request.include_vitals and ("高热" in text or "39" in text or "40" in text):
            return "high"
        if any(keyword in text for keyword in MEDIUM_KEYWORDS):
            return "medium"
        return "low"

    def _candidate_medicines(self, categories: list[str], allergy_text: str) -> list[Medicine]:
        stocked = [medicine for medicine in self.medicine_repository.list_all() if medicine.stock > 0]
        category_set = {category for category in categories if category != "解热镇痛"}
        if "解热镇痛" in categories:
            category_set.add("感冒发热")
        candidates = [medicine for medicine in stocked if medicine.category in category_set and medicine.is_otc]
        return [medicine for medicine in candidates if not self._conflicts_with_allergy(medicine, allergy_text)]

    def candidate_medicines_for(self, categories: list[str], allergy_text: str) -> list[CandidateMedicine]:
        return [self._to_candidate(medicine) for medicine in self._candidate_medicines(categories, allergy_text)]

    def _conflicts_with_allergy(self, medicine: Medicine, allergy_text: str) -> bool:
        for allergy_keyword, medicine_keywords in MEDICINE_CONFLICT_KEYWORDS.items():
            if allergy_keyword in allergy_text and any(keyword in medicine.name for keyword in medicine_keywords):
                return True
        return False

    def _to_candidate(self, medicine: Medicine) -> CandidateMedicine:
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
        )

    def _risk_label(self, risk_level: RiskLevel) -> str:
        labels = {
            "low": "低风险",
            "medium": "中风险",
            "high": "高风险",
            "emergency": "紧急风险",
        }
        return labels[risk_level]

    def _summary(self, request: InquiryEvaluateRequest) -> str:
        parts = [request.symptoms_text.strip()]
        if request.duration.strip():
            parts.append(f"持续时间：{request.duration.strip()}")
        if request.used_medicines.strip():
            parts.append(f"已用药：{request.used_medicines.strip()}")
        if request.allergy_or_contraindication.strip():
            parts.append(f"过敏/禁忌：{request.allergy_or_contraindication.strip()}")
        return "；".join(parts)

    def _safety_notice(self, risk_level: RiskLevel, can_proceed: bool, categories: list[str]) -> str:
        if risk_level in {"high", "emergency"}:
            return "存在明显高风险信号，本系统不进入取药确认，请立即联系医生或救援人员。"
        if risk_level == "medium":
            return "当前信息存在不确定或持续症状，本系统仅提供风险提示，请先联系医生、家人或远程协助人员。"
        if "家庭常用" in categories:
            return "慢病相关药品需按已有计划或医嘱核验，本次问询不直接进入取药确认。"
        if can_proceed:
            return "当前仅可查看候选药品类别和安全提示，后续取药仍需完成用药安全核验。"
        return "已识别过敏或禁忌信息，请先由医生或远程协助人员核验。"

    def _next_steps(self, risk_level: RiskLevel, can_proceed: bool, categories: list[str]) -> list[str]:
        if risk_level == "emergency":
            return ["立即联系医生或救援人员", "保持现场有人陪同", "不要自行取药处理"]
        if risk_level == "high":
            return ["尽快联系医生或救援人员", "由家人陪同观察", "暂不进入取药确认"]
        if risk_level == "medium":
            return ["联系医生或远程协助人员", "补充体征和既往用药信息", "暂不进入取药确认"]
        if "家庭常用" in categories:
            return ["核对已有用药计划或医嘱", "由医生或家人确认后再处理"]
        if can_proceed:
            return ["查看候选药品类别和安全提示", "在药品页完成用药安全核验", "通过取药确认流程记录操作"]
        return ["先核验过敏/禁忌信息", "必要时联系医生或远程协助人员"]
