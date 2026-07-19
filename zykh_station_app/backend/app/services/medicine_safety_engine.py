from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..config import settings
from ..schemas.inquiry import InquiryExtractedInformation, RiskLevel
from .medicine_knowledge_repository import MedicineKnowledgeRepository


EMERGENCY_TERMS = ("意识不清", "昏迷", "抽搐", "严重过敏", "大出血", "口角歪斜", "单侧肢体无力")
HIGH_TERMS = ("高热不退", "持续胸闷", "胸闷气短", "剧烈疼痛", "呕血", "黑便", "严重外伤")


@dataclass(frozen=True)
class HardSafetyDecision:
    risk_level: RiskLevel
    risk_reasons: list[str]


class MedicineSafetyEngine:
    def __init__(self, knowledge: MedicineKnowledgeRepository | None = None) -> None:
        self.knowledge = knowledge or MedicineKnowledgeRepository()

    def assess_guardrails(
        self,
        extracted: InquiryExtractedInformation,
        vitals: dict[str, Any] | None,
        *,
        ai_risk_level: RiskLevel | None = None,
        ai_risk_reasons: list[str] | None = None,
    ) -> HardSafetyDecision:
        """Apply only non-negotiable safety rules; semantic judgment remains with AI."""
        text = "；".join(
            part
            for part in (
                extracted.symptoms_text,
                extracted.case_summary,
                "；".join(
                    observation.evidence
                    for observation in extracted.observations
                    if observation.status == "present"
                ),
            )
            if part
        )
        level: RiskLevel = "low"
        reasons: list[str] = []
        spo2 = self._vital_number(vitals, "spo2")
        temperature = self._vital_number(vitals, "temperature")
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
            reasons.append("出现持续或严重危险表现")
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

        order = {"low": 0, "medium": 1, "high": 2, "emergency": 3}
        if ai_risk_level in order and order[ai_risk_level] > order[level]:
            level = ai_risk_level
            reasons.extend(
                reason.strip()
                for reason in (ai_risk_reasons or [])
                if reason and reason.strip()
            )
        if not reasons:
            reasons.append("未触发硬性危险信号")
        return HardSafetyDecision(level, list(dict.fromkeys(reasons)))

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
