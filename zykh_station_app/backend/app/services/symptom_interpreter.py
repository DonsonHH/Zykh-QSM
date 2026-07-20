from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from ..schemas.inquiry import InquiryHistoryRelationship, InquiryObservation, RiskLevel
from .ai_service import AiService


ALLOWED_ACTION_INTENTS = {"ask", "measure_vitals", "analyze", "escalate", "end"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "emergency"}
UNSAFE_HARDWARE_LANGUAGE = ("打开药柜", "开柜", "出药", "发药")


@dataclass
class SymptomInterpretation:
    case_summary: str = ""
    observations: list[InquiryObservation] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    history_relationship: InquiryHistoryRelationship = field(default_factory=InquiryHistoryRelationship)
    duration: str = ""
    used_medicines: str = ""
    allergy_or_contraindication: str = ""
    follow_up_question: str = ""
    assistant_reply: str = ""
    reasoning_summary: str = ""
    action_intent: str = "ask"
    action_reason: str = ""
    ai_risk_level: RiskLevel | None = None
    risk_signals: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "ai_unavailable"
    available: bool = True

    @property
    def symptom_dimensions(self) -> list[str]:
        """Compatibility view for existing admin and inquiry presentation components."""
        return list(
            dict.fromkeys(
                observation.concept
                for observation in self.observations
                if observation.status == "present"
            )
        )

    @property
    def dimension_evidence(self) -> dict[str, str]:
        return {
            observation.concept: observation.evidence
            for observation in self.observations
            if observation.status == "present" and observation.evidence
        }

    @property
    def symptom_features(self) -> list[str]:
        return []

    @property
    def feature_evidence(self) -> dict[str, str]:
        return {}


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
        payload = self.ai_service.extract_inquiry_information(transcript, existing, profile)
        if not payload.get("ok"):
            return SymptomInterpretation(
                assistant_reply="刚才这句话没有整理完整，请换一种说法再说一次。",
                reasoning_summary=str(payload.get("message") or "云端与本地问询模型均未返回有效内容。")[:180],
                action_intent="ask",
                action_reason="等待用户换一种说法补充本轮内容",
                source="assistant",
                available=False,
            )
        interpretation = self._validated_model_result(payload, existing)
        self._complete_explicit_answers(interpretation, transcript, existing)
        return interpretation

    def resume_after_vitals(
        self,
        existing: dict[str, Any],
        profile: dict[str, Any],
    ) -> SymptomInterpretation:
        return self.interpret("体征测量已经完成，请结合本次结果继续问询。", existing, profile)

    def rank_candidates(self, context: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        ranker = getattr(self.ai_service, "rank_inquiry_candidates", None)
        if not callable(ranker):
            return {"ok": False, "source": "ai_unavailable"}
        return ranker(context, candidates)

    def opening_question(self, profile: dict[str, Any], fallback: str) -> tuple[str, str]:
        generator = getattr(self.ai_service, "generate_inquiry_opening", None)
        if not callable(generator):
            return fallback, "assistant"
        result = generator(
            str(profile.get("name") or "访客"),
            bool(profile.get("profile") or profile.get("allergies")),
        )
        if result.get("ok") and str(result.get("reply") or "").strip():
            return str(result["reply"]).strip(), str(result.get("source") or "cloud")
        return fallback, "assistant"

    def explain_recommendation(self, context: dict[str, Any]) -> dict[str, Any]:
        generator = getattr(self.ai_service, "generate_inquiry_recommendation", None)
        if not callable(generator):
            return {"ok": False, "source": "assistant"}
        return generator(context)

    @classmethod
    def _validated_model_result(
        cls,
        payload: dict[str, Any],
        existing: dict[str, Any],
    ) -> SymptomInterpretation:
        max_turn = max(int(existing.get("conversation_turns") or 0), 1)
        observations: list[InquiryObservation] = []
        for raw in payload.get("observations") or []:
            if not isinstance(raw, dict):
                continue
            concept = cls._short_text(raw.get("concept"), 80)
            status = str(raw.get("status") or "uncertain").strip()
            evidence = cls._short_text(raw.get("evidence"), 180)
            try:
                source_turn = max(0, min(int(raw.get("source_turn") or max_turn), max_turn))
                confidence = max(0.0, min(float(raw.get("confidence") or 0), 1.0))
            except (TypeError, ValueError):
                continue
            if not concept or status not in {"present", "absent", "uncertain"}:
                continue
            observations.append(
                InquiryObservation(
                    concept=concept,
                    status=status,
                    evidence=evidence,
                    source_turn=source_turn,
                    confidence=confidence,
                )
            )

        raw_history = payload.get("history_relationship")
        raw_history = raw_history if isinstance(raw_history, dict) else {}
        history = InquiryHistoryRelationship(
            related=bool(raw_history.get("related")),
            similarities=cls._text_list(raw_history.get("similarities"), 5, 100),
            important_changes=cls._text_list(raw_history.get("important_changes"), 5, 100),
            should_reuse_previous_conclusion=False,
        )
        action = str(payload.get("next_action") or payload.get("action_intent") or "ask").strip()
        if action not in ALLOWED_ACTION_INTENTS:
            action = "ask"
        risk = str(payload.get("risk_level") or "").strip()
        ai_risk_level: RiskLevel | None = risk if risk in ALLOWED_RISK_LEVELS else None  # type: ignore[assignment]
        assistant_reply = cls._short_text(
            payload.get("assistant_reply") or payload.get("next_question"),
            240,
        )
        if any(term in assistant_reply for term in UNSAFE_HARDWARE_LANGUAGE):
            assistant_reply = "我还需要继续确认你的情况，请再补充一项最重要的信息。"
            action = "ask"
        try:
            confidence = max(0.0, min(float(payload.get("confidence") or 0), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        case_summary = cls._short_text(payload.get("case_summary"), 260)
        return SymptomInterpretation(
            case_summary=case_summary,
            observations=observations,
            uncertainties=cls._text_list(payload.get("uncertainties"), 8, 120),
            history_relationship=history,
            duration=cls._short_text(payload.get("duration"), 120),
            used_medicines=cls._short_text(payload.get("used_medicines"), 180),
            allergy_or_contraindication=cls._short_text(
                payload.get("allergy_or_contraindication"),
                180,
            ),
            follow_up_question=cls._short_text(
                payload.get("next_question") or payload.get("follow_up_question"),
                160,
            ),
            assistant_reply=assistant_reply,
            reasoning_summary=case_summary or cls._short_text(payload.get("reason"), 180),
            action_intent=action,
            action_reason=cls._short_text(payload.get("reason"), 160),
            ai_risk_level=ai_risk_level,
            risk_signals=cls._text_list(payload.get("risk_signals"), 8, 100),
            confidence=confidence,
            source=str(payload.get("source") or "cloud"),
            available=True,
        )

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
            "没有使用药物", "还没有使用药物", "未使用", "未用药",
            "什么药都没用", "什么药都没有用", "暂时还没有",
        )
        if any(term in text for term in negative) or (
            allow_short_answer and text in {"没有", "还没有", "没", "暂时没有"}
        ):
            return "未使用"
        if any(term in text for term in ("吃过", "用过", "已经吃", "已经用", "已使用")):
            return text[:120] if len(text) > 4 else "已使用"
        return ""

    @staticmethod
    def allergy_answer(transcript: str, *, allow_short_answer: bool = False) -> str:
        text = transcript.strip()
        if any(term in text for term in ("不知道", "不清楚", "不确定", "不能明确", "无法确认", "记不清")):
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
            direct_allergy = re.search(r"对([^，。；、\s]{1,16})过敏", text)
            if direct_allergy:
                return f"{direct_allergy.group(1)}过敏"
            return text[:120]
        return ""

    @classmethod
    def _complete_explicit_answers(
        cls,
        interpretation: SymptomInterpretation,
        transcript: str,
        existing: dict[str, Any],
    ) -> None:
        interpretation.duration = (
            interpretation.duration
            or cls.duration_answer(transcript)
            or str(existing.get("duration") or "").strip()
        )
        interpretation.used_medicines = (
            interpretation.used_medicines
            or cls.used_medicine_answer(transcript)
            or str(existing.get("used_medicines") or "").strip()
        )
        interpretation.allergy_or_contraindication = (
            interpretation.allergy_or_contraindication
            or cls.allergy_answer(transcript)
            or str(existing.get("allergy_or_contraindication") or "").strip()
        )

        question = interpretation.follow_up_question or interpretation.assistant_reply
        asks_answered_field = (
            bool(interpretation.duration)
            and any(term in question for term in ("持续", "多久", "多长时间"))
        ) or (
            bool(interpretation.used_medicines)
            and any(term in question for term in ("用过药", "用药", "吃过药", "吃药"))
        ) or (
            bool(interpretation.allergy_or_contraindication)
            and any(term in question for term in ("过敏", "禁忌", "不能使用"))
        )
        if interpretation.action_intent != "ask" or not asks_answered_field:
            return
        if not interpretation.used_medicines:
            next_question = "这次不舒服以后有没有用过药？"
        elif not interpretation.allergy_or_contraindication:
            next_question = "有没有药物过敏或明确不能使用的药？"
        else:
            interpretation.action_intent = "analyze"
            interpretation.follow_up_question = ""
            interpretation.assistant_reply = "信息已经整理好了，我来结合当前情况继续分析。"
            return
        interpretation.follow_up_question = next_question
        interpretation.assistant_reply = next_question

    @staticmethod
    def _short_text(value: object, limit: int) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

    @classmethod
    def _text_list(cls, value: object, max_items: int, max_length: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            text
            for item in value[:max_items]
            if (text := cls._short_text(item, max_length))
        ]

    @staticmethod
    def _has_unnegated_term(text: str, term: str) -> bool:
        for match in re.finditer(re.escape(term), text):
            prefix = text[max(0, match.start() - 8):match.start()]
            clause = re.split(r"[，。；、,;!?！？]", prefix)[-1]
            if re.search(r"(?:没有|没|无|否认|未见|不伴|并无|不太|不)\s*$", clause):
                continue
            return True
        return False
