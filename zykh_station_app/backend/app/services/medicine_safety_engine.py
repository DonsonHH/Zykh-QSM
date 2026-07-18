from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..config import settings
from ..schemas.inquiry import CandidateMedicine, InquiryExtractedInformation, RiskLevel, TreatmentOption
from .medicine_knowledge_repository import MedicineKnowledgeRepository


EMERGENCY_TERMS = ("意识不清", "昏迷", "抽搐", "严重过敏", "大出血", "口角歪斜", "单侧肢体无力")
HIGH_TERMS = ("高热不退", "持续胸闷", "剧烈疼痛", "呕血", "黑便", "严重外伤")


@dataclass(frozen=True)
class SafetyDecision:
    risk_level: RiskLevel
    risk_reasons: list[str]
    primary_candidate: CandidateMedicine | None
    alternative_candidate: CandidateMedicine | None
    treatment_options: list[TreatmentOption]


class MedicineSafetyEngine:
    def __init__(self, knowledge: MedicineKnowledgeRepository | None = None) -> None:
        self.knowledge = knowledge or MedicineKnowledgeRepository()

    def assess(
        self,
        extracted: InquiryExtractedInformation,
        vitals: dict[str, Any] | None,
        profile_context: str = "",
        history_medicine_counts: dict[str, int] | None = None,
    ) -> SafetyDecision:
        text = extracted.symptoms_text
        level: RiskLevel = "low"
        reasons: list[str] = []
        spo2 = self._vital_number(vitals, "spo2")
        temperature = self._vital_number(vitals, "temperature")
        heart_rate = self._vital_number(vitals, "heart_rate")
        chest_pain = self._has_unnegated_term(text, "胸痛")
        breathing_difficulty = self._has_unnegated_term(text, "呼吸困难")
        if (chest_pain and breathing_difficulty) or any(
            self._has_unnegated_term(text, term) for term in EMERGENCY_TERMS
        ):
            level = "emergency"
            reasons.append("出现需要立即线下处理的危险信号")
        elif spo2 is not None and spo2 < settings.inquiry_spo2_emergency_below:
            level = "emergency"
            reasons.append(f"血氧低于 {settings.inquiry_spo2_emergency_below:g}%")
        elif any(self._has_unnegated_term(text, term) for term in HIGH_TERMS):
            level = "high"
            reasons.append("症状包含高风险持续或严重表现")
        elif (
            spo2 is not None
            and settings.inquiry_spo2_emergency_below <= spo2 <= settings.inquiry_spo2_high_max
        ):
            level = "high"
            reasons.append(
                f"稳定复测血氧在 {settings.inquiry_spo2_emergency_below:g}%–"
                f"{settings.inquiry_spo2_high_max:g}%"
            )
        elif temperature is not None and temperature >= settings.inquiry_temperature_high_at:
            level = "high"
            reasons.append(f"额温达到或超过 {settings.inquiry_temperature_high_at:g}℃")
        elif (
            self._has_unnegated_term(text, "头晕")
            or self._long_duration(extracted.duration)
            or "加重" in extracted.clarification_answers.get("history_change", "")
            or extracted.confidence < settings.inquiry_medium_confidence_below
        ):
            level = "medium"
            reasons.append("仍有持续症状或信息不确定性")
        else:
            reasons.append("未发现明确高危信号")

        if temperature is not None and heart_rate is not None and spo2 is not None:
            reasons.append(
                f"本次额温 {temperature:g}℃、心率 {heart_rate:g} 次/分、血氧 {spo2:g}% 已纳入安全核验"
            )

        if level in {"high", "emergency"}:
            return SafetyDecision(level, reasons, None, None, [])
        context_text = "；".join(
            value for value in (profile_context.strip(), extracted.allergy_or_contraindication.strip()) if value
        )
        options = self.knowledge.treatment_options(
            extracted.symptom_dimensions,
            context_text,
            symptom_features=extracted.symptom_features,
            history_medicine_counts=history_medicine_counts,
        )
        primary = self._candidate(options[0].medicines[0]) if options and options[0].medicines else None
        alternative = None
        if len(options) > 1:
            alternative = next(
                (
                    self._candidate(medicine)
                    for medicine in options[1].medicines
                    if primary is None or medicine.id != primary.id
                ),
                None,
            )
        return SafetyDecision(level, reasons, primary, alternative, options)

    @staticmethod
    def _candidate(value) -> CandidateMedicine:
        return CandidateMedicine(
            id=value.id,
            name=value.name,
            category=value.category,
            slot=value.slot,
            stock=value.stock,
            unit=value.unit,
            safety_note=value.safety_note,
            indications=value.indications,
            dosage=value.dosage,
            match_reason=value.match_reason,
            requires_existing_direction=value.requires_existing_direction,
        )

    @staticmethod
    def _long_duration(duration: str) -> bool:
        return any(term in duration for term in ("三天", "3天", "一周", "持续很久", "超过三天"))

    @staticmethod
    def _vital_number(vitals: dict[str, Any] | None, key: str) -> float | None:
        if not vitals:
            return None
        try:
            value = float(vitals.get(key))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _has_unnegated_term(text: str, term: str) -> bool:
        for match in re.finditer(re.escape(term), text):
            prefix = text[max(0, match.start() - 8):match.start()]
            clause = re.split(r"[，。；、,;!?！？]", prefix)[-1]
            if re.search(r"(?:没有|没|无|否认|未见|不伴|并无)\s*$", clause):
                continue
            return True
        return False
