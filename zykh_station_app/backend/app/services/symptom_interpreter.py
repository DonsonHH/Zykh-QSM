from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .ai_service import AiService


ALLOWED_DIMENSIONS = {
    "感冒鼻部症状",
    "发热全身不适",
    "咳嗽咳痰",
    "咽喉口腔不适",
    "恶心暑湿",
    "腹泻肠道不适",
    "便秘",
    "胃酸胃部不适",
    "过敏瘙痒",
    "轻微外伤",
    "皮肤真菌不适",
    "肌肉关节疼痛",
    "干眼不适",
    "鼻炎过敏",
    "营养补充",
    "慢病既往用药",
}

ALLOWED_ACTION_INTENTS = {"ask", "measure_vitals", "analyze"}
VITALS_SENSITIVE_DIMENSIONS = {"发热全身不适", "咳嗽咳痰", "恶心暑湿"}


DIMENSION_KEYWORDS = {
    "恶心暑湿": ("中暑", "暑湿", "恶心", "头晕", "胸闷腹胀"),
    "感冒鼻部症状": ("流清鼻涕", "清鼻涕", "流鼻涕", "流涕", "鼻塞", "打喷嚏", "风寒"),
    "发热全身不适": ("发热", "发烧", "头痛", "乏力", "身痛", "畏寒"),
    "咳嗽咳痰": ("咳嗽", "咳痰", "痰多"),
    "咽喉口腔不适": ("咽痛", "喉咙痛", "口腔溃疡", "咽喉"),
    "腹泻肠道不适": ("腹泻", "拉肚子", "水样便"),
    "便秘": ("便秘", "排便困难"),
    "胃酸胃部不适": ("胃痛", "胃酸", "反酸", "烧心", "胃胀"),
    "过敏瘙痒": ("过敏", "瘙痒", "皮疹", "荨麻疹"),
    "轻微外伤": ("擦伤", "破皮", "小伤口", "划伤"),
    "皮肤真菌不适": ("脚气", "真菌", "癣"),
    "肌肉关节疼痛": ("肌肉痛", "关节痛", "扭伤"),
    "干眼不适": ("眼干", "干眼", "眼涩"),
    "鼻炎过敏": ("鼻炎", "过敏性鼻炎"),
    "营养补充": ("维生素", "营养补充"),
    "慢病既往用药": ("高血压", "血压高", "降压药", "慢病用药", "长期用药"),
}


@dataclass
class SymptomInterpretation:
    symptom_dimensions: list[str] = field(default_factory=list)
    dimension_evidence: dict[str, str] = field(default_factory=dict)
    duration: str = ""
    used_medicines: str = ""
    allergy_or_contraindication: str = ""
    follow_up_question: str = ""
    reasoning_summary: str = ""
    action_intent: str = "ask"
    action_reason: str = ""
    confidence: float = 0.0
    source: str = "rules_fallback"


class SymptomInterpreter:
    def __init__(self, ai_service: AiService | None = None) -> None:
        self.ai_service = ai_service or AiService()

    def interpret(
        self,
        transcript: str,
        existing: dict[str, Any] | None = None,
        profile: dict[str, Any] | None = None,
    ) -> SymptomInterpretation:
        existing = existing or {}
        profile = profile or {}
        model = self.ai_service.extract_inquiry_information(transcript, existing, profile)
        if model.get("ok"):
            validated = self._validated_model_result(model, transcript)
            if validated.symptom_dimensions or any(
                (validated.duration, validated.used_medicines, validated.allergy_or_contraindication)
            ):
                return validated
        return self._rules_interpret(transcript)

    def _validated_model_result(self, payload: dict[str, Any], transcript: str) -> SymptomInterpretation:
        rules = self._rules_interpret(transcript)
        evidence = payload.get("dimension_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        dimensions: list[str] = list(rules.symptom_dimensions)
        clean_evidence: dict[str, str] = dict(rules.dimension_evidence)
        for raw_dimension in payload.get("symptom_dimensions") or []:
            dimension = str(raw_dimension).strip()
            quote = str(evidence.get(dimension) or "").strip()
            if dimension not in ALLOWED_DIMENSIONS or not quote or quote not in transcript:
                continue
            if not any(
                self._has_unnegated_term(quote, keyword)
                for keyword in DIMENSION_KEYWORDS.get(dimension, ())
            ):
                continue
            dimensions.append(dimension)
            clean_evidence[dimension] = quote
        try:
            confidence = max(0.0, min(float(payload.get("confidence") or 0), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        action_intent = str(payload.get("action_intent") or "ask").strip()
        if action_intent not in ALLOWED_ACTION_INTENTS:
            action_intent = "ask"
        return SymptomInterpretation(
            symptom_dimensions=list(dict.fromkeys(dimensions)),
            dimension_evidence=clean_evidence,
            duration=rules.duration or self._verbatim_value(payload.get("duration"), transcript),
            used_medicines=rules.used_medicines or self._verbatim_value(payload.get("used_medicines"), transcript),
            allergy_or_contraindication=(
                rules.allergy_or_contraindication
                or self._verbatim_value(payload.get("allergy_or_contraindication"), transcript)
            ),
            follow_up_question=str(payload.get("follow_up_question") or "").strip(),
            reasoning_summary=self._short_text(payload.get("reasoning_summary"), 180),
            action_intent=action_intent,
            action_reason=self._short_text(payload.get("action_reason"), 120),
            confidence=confidence,
            source=str(payload.get("source") or "cloud"),
        )

    def _rules_interpret(self, transcript: str) -> SymptomInterpretation:
        dimensions: list[str] = []
        evidence: dict[str, str] = {}
        for dimension, keywords in DIMENSION_KEYWORDS.items():
            match = next((keyword for keyword in keywords if self._has_unnegated_term(transcript, keyword)), "")
            if match:
                dimensions.append(dimension)
                evidence[dimension] = match
        duration = self.duration_answer(transcript)
        used = self.used_medicine_answer(transcript)
        allergy = self.allergy_answer(transcript)
        if VITALS_SENSITIVE_DIMENSIONS.intersection(dimensions):
            action_intent = "measure_vitals"
            action_reason = "核心体征会影响本次风险核验"
        elif dimensions:
            action_intent = "analyze"
            action_reason = "已识别到可由本地安全规则核验的症状维度"
        else:
            action_intent = "ask"
            action_reason = "仍需补充明确的症状信息"
        return SymptomInterpretation(
            symptom_dimensions=dimensions,
            dimension_evidence=evidence,
            duration=duration,
            used_medicines=used,
            allergy_or_contraindication=allergy,
            reasoning_summary="已按用户原话整理症状证据。" if dimensions else "本轮未提取到明确症状证据。",
            action_intent=action_intent,
            action_reason=action_reason,
            confidence=0.7 if dimensions else 0.2,
            source="rules_fallback",
        )

    @staticmethod
    def _first_match(text: str, candidates: tuple[str, ...]) -> str:
        return next((item for item in candidates if item in text), "")

    @staticmethod
    def duration_answer(transcript: str) -> str:
        text = transcript.strip()
        if not text:
            return ""
        match = re.search(
            r"(?:刚刚|刚才|刚开始|没多久|持续很久|今天|昨晚|昨天|前天|去年|前年|上周|上个月|"
            r"(?:大约|大概|差不多)?(?:半|[零一二两三四五六七八九十百\d]+)"
            r"(?:秒钟?|分钟?|小时|钟头|天|周|星期|个月|月|年)(?:半|左右|上下|多)?)",
            text,
        )
        if not match:
            return ""
        value = match.group(0)
        for prefix in ("大约", "大概", "差不多"):
            value = value.removeprefix(prefix)
        return value

    @classmethod
    def used_medicine_answer(cls, transcript: str, *, allow_short_answer: bool = False) -> str:
        text = transcript.strip()
        negative = (
            "没吃药", "没有吃药", "没吃过药", "没有吃过药", "还没吃药", "还没吃过药",
            "没用药", "没有用药", "没用过药", "没有用过药", "还没用药", "还没用过药",
            "未使用", "未用药", "什么药都没用", "什么药都没有用", "暂时还没有",
        )
        if any(term in text for term in negative) or (
            allow_short_answer and text in {"没有", "还没有", "没", "暂时没有"}
        ):
            return "未使用"
        if any(cls._has_unnegated_term(text, term) for term in ("吃过", "用过", "已经吃", "已经用", "已使用")):
            return text[:120] if len(text) > 4 else "已使用"
        return ""

    @staticmethod
    def allergy_answer(transcript: str, *, allow_short_answer: bool = False) -> str:
        text = transcript.strip()
        uncertain = ("不知道", "不清楚", "不确定", "不能明确", "无法确认", "记不清")
        if any(term in text for term in uncertain):
            return "不确定"
        negative = (
            "没有过敏", "没有药物过敏", "无过敏", "无药物过敏", "没有禁忌", "无禁忌",
            "没有不能用的药", "没有不能使用的药",
        )
        if any(term in text for term in negative) or (
            allow_short_answer and text in {"没有", "还没有", "没", "无"}
        ):
            return "无"
        if "过敏" in text or "禁忌" in text or "不能用" in text or "不能使用" in text:
            return text[:120]
        return ""

    @staticmethod
    def _verbatim_value(value: object, transcript: str) -> str:
        normalized = str(value or "").strip()
        return normalized if normalized and normalized in transcript else ""

    @staticmethod
    def _short_text(value: object, limit: int) -> str:
        return str(value or "").strip()[:limit]

    @staticmethod
    def _has_unnegated_term(text: str, term: str) -> bool:
        for match in re.finditer(re.escape(term), text):
            prefix = text[max(0, match.start() - 8):match.start()]
            clause = re.split(r"[，。；、,;!?！？]", prefix)[-1]
            if re.search(r"(?:没有|没|无|否认|未见|不伴|并无)\s*$", clause):
                continue
            return True
        return False
