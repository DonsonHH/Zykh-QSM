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
}


DIMENSION_KEYWORDS = {
    "恶心暑湿": ("中暑", "暑湿", "恶心", "头晕", "胸闷腹胀"),
    "感冒鼻部症状": ("流鼻涕", "流涕", "鼻塞", "打喷嚏", "风寒"),
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
}


@dataclass
class SymptomInterpretation:
    symptom_dimensions: list[str] = field(default_factory=list)
    dimension_evidence: dict[str, str] = field(default_factory=dict)
    duration: str = ""
    used_medicines: str = ""
    allergy_or_contraindication: str = ""
    follow_up_question: str = ""
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
        dimensions: list[str] = []
        clean_evidence: dict[str, str] = {}
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
        duration = self._first_match(
            transcript,
            ("刚开始", "半天", "一天", "1天", "两天", "2天", "三天", "3天", "一周", "持续很久"),
        )
        used = ""
        if any(term in transcript for term in ("没吃药", "没有吃药", "未使用", "还没用药")):
            used = "未使用"
        elif any(term in transcript for term in ("吃过", "用过", "已经吃", "已使用")):
            used = "已使用"
        allergy = ""
        if any(term in transcript for term in ("没有过敏", "无过敏", "没有禁忌")):
            allergy = "无"
        elif "过敏" in transcript or "禁忌" in transcript:
            allergy = transcript[:120]
        return SymptomInterpretation(
            symptom_dimensions=dimensions,
            dimension_evidence=evidence,
            duration=duration,
            used_medicines=used,
            allergy_or_contraindication=allergy,
            confidence=0.7 if dimensions else 0.2,
            source="rules_fallback",
        )

    @staticmethod
    def _first_match(text: str, candidates: tuple[str, ...]) -> str:
        return next((item for item in candidates if item in text), "")

    @staticmethod
    def _verbatim_value(value: object, transcript: str) -> str:
        normalized = str(value or "").strip()
        return normalized if normalized and normalized in transcript else ""

    @staticmethod
    def _has_unnegated_term(text: str, term: str) -> bool:
        for match in re.finditer(re.escape(term), text):
            prefix = text[max(0, match.start() - 8):match.start()]
            clause = re.split(r"[，。；、,;!?！？]", prefix)[-1]
            if re.search(r"(?:没有|没|无|否认|未见|不伴|并无)\s*$", clause):
                continue
            return True
        return False
