from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from ..schemas.inquiry import InquiryHistoryRelationship, InquiryObservation, RiskLevel
from .ai_service import AiService
from .inquiry_dialogue_policy import (
    normalize_answered_topics,
    normalize_question_topic,
    normalize_topic_evidence,
    symptom_scope_explicitly_complete,
)
from .spoken_answer import is_contextual_negative_answer


ALLOWED_ACTION_INTENTS = {"ask", "measure_vitals", "analyze", "escalate", "end"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "emergency"}
ALLOWED_CHANGE_TYPES = {"none", "add", "refine", "replace"}
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
    answered_topics_this_turn: list[str] = field(default_factory=list)
    topic_evidence: dict[str, str] = field(default_factory=dict)
    question_topic: str = ""
    clinical_ready: bool = False
    material_symptom_change: bool = False
    symptom_change_type: str = "none"
    replaced_concepts: list[str] = field(default_factory=list)
    symptom_scope_complete: bool = False
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
                assistant_reply="我已经保留你刚才的话，正在根据现有信息继续核对。",
                reasoning_summary=str(payload.get("message") or "云端与本地问询模型均未返回有效内容。")[:180],
                action_intent="ask",
                action_reason="语义服务暂时不可用，改用本地问句策略继续",
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
        change_type = str(payload.get("symptom_change_type") or "none").strip().lower()
        if change_type not in ALLOWED_CHANGE_TYPES:
            change_type = "none"
        material_change = cls._bool_value(payload.get("material_symptom_change")) or change_type == "replace"
        if change_type == "refine":
            # A more precise description of the same complaint must not let a
            # model-provided material flag reopen the four-question budget.
            material_change = False
        elif material_change and change_type == "none":
            # Preserve the legacy correction fallback without rewriting an
            # explicit material ``add`` into ``replace`` and dropping the old
            # complaint at the orchestration boundary.
            change_type = "replace"
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
            answered_topics_this_turn=normalize_answered_topics(
                payload.get("answered_topics_this_turn")
            ),
            topic_evidence=normalize_topic_evidence(payload.get("topic_evidence")),
            question_topic=normalize_question_topic(payload.get("question_topic")),
            clinical_ready=cls._bool_value(payload.get("clinical_ready")),
            material_symptom_change=material_change,
            symptom_change_type=change_type,
            replaced_concepts=cls._text_list(payload.get("replaced_concepts"), 4, 80),
            # Whether the user has finished listing concurrent symptoms is a
            # dialogue-state fact, not a clinical inference.  A model may
            # optimistically mark an ordinary first complaint as complete and
            # thereby skip the required scope-confirmation question.  Start
            # closed here; _complete_explicit_answers() opens it only for an
            # explicit phrase ("没有别的" etc.) or a direct answer to the
            # pending additional-symptoms question.
            symptom_scope_complete=False,
            confidence=confidence,
            source=str(payload.get("source") or "cloud"),
            available=True,
        )

    @staticmethod
    def duration_answer(transcript: str) -> str:
        text = transcript.strip()
        if not text:
            return ""
        named_times = (
            ("昨天晚上", "昨晚开始"),
            ("昨晚", "昨晚开始"),
            ("昨天下午", "昨天下午开始"),
            ("昨天中午", "昨天中午开始"),
            ("昨天早上", "昨天早上开始"),
            ("今天早上", "今天早上开始"),
            ("今早", "今天早上开始"),
            ("早上起床", "今天早上开始"),
            ("今天中午", "今天中午开始"),
            ("中午", "今天中午开始"),
            ("今天下午", "今天下午开始"),
            ("下午", "今天下午开始"),
            ("今天晚上", "今天晚上开始"),
            ("晚上", "今天晚上开始"),
            ("早晨", "今天早上开始"),
            ("刚刚", "刚刚开始"),
            ("刚才", "刚才开始"),
        )
        for token, normalized in named_times:
            if token in text:
                return normalized
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
        if any(
            term in text
            for term in (
                "记不清药名", "不知道药名", "不清楚药名", "药名不详", "说不出药名",
                "不知道吃的什么", "不清楚吃的什么", "吃过但不记得", "用过但不记得",
            )
        ):
            return "不确定"
        negative = (
            "没吃药", "没有吃药", "没吃过药", "没有吃过药", "还没吃药", "还没吃过药",
            "没用药", "没有用药", "没用过药", "没有用过药", "还没用药", "还没用过药",
            "没有使用药物", "还没有使用药物", "未使用", "未用药",
            "什么药都没用", "什么药都没有用", "暂时还没有", "哪有那么快吃药",
            "哪有这么快吃药", "还没来得及吃药", "没来得及吃药",
        )
        if any(term in text for term in negative) or (
            allow_short_answer and is_contextual_negative_answer(text)
        ):
            return "未使用"
        if any(term in text for term in ("吃过", "用过", "已经吃", "已经用", "已使用")):
            return text[:120] if len(text) > 4 else "已使用"
        return ""

    @staticmethod
    def allergy_answer(transcript: str, *, allow_short_answer: bool = False) -> str:
        text = transcript.strip()
        if any(
            phrase in text
            for phrase in ("什么意思", "什么算", "有哪些", "怎么回答", "没听懂", "为什么要问")
        ):
            return ""
        if any(term in text for term in ("不知道", "不清楚", "不确定", "不能明确", "无法确认", "记不清", "不详")):
            return "不确定"
        negative = (
            "没有过敏", "没有药物过敏", "无过敏", "无药物过敏", "没有禁忌", "无禁忌",
            "没啥过敏", "没什么过敏", "没有什么过敏", "没有不能用的药", "没有不能使用的药",
        )
        if any(term in text for term in negative) or (
            allow_short_answer and is_contextual_negative_answer(text)
        ):
            return "无"
        if "过敏" in text or "禁忌" in text or "不能用" in text or "不能使用" in text:
            direct_allergy = re.search(r"对([^，。；、\s]{1,16})过敏", text)
            if direct_allergy:
                return f"{direct_allergy.group(1)}过敏"
            return text[:120]
        if (
            allow_short_answer
            and re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9＋+·\-]{2,20}", text)
            and text not in {"有的", "确实有", "是的", "对的"}
        ):
            # The preceding question already supplies the semantic subject:
            # “对什么药过敏？” + “银黄颗粒” means “银黄颗粒过敏”.
            return f"{text}过敏"
        return ""

    @classmethod
    def _complete_explicit_answers(
        cls,
        interpretation: SymptomInterpretation,
        transcript: str,
        existing: dict[str, Any],
    ) -> None:
        pending_field = cls._pending_answer_field(existing)
        contextual_short_answer = cls._is_contextual_short_answer(transcript, pending_field)
        if contextual_short_answer:
            interpretation.observations = []
            interpretation.case_summary = str(existing.get("case_summary") or "").strip()
        safety_answer_pending = pending_field in {
            "used_medicines",
            "allergy_or_contraindication",
        }
        explicit_duration = "" if safety_answer_pending else cls.duration_answer(transcript)
        if safety_answer_pending:
            interpretation.duration = str(existing.get("duration") or "").strip()

        mentions_allergy = any(
            term in transcript
            for term in ("过敏", "禁忌", "不能用", "不能使用", "不耐受")
        )
        mentions_medicine_use = any(
            term in transcript
            for term in (
                "吃过", "吃了", "服用", "服过", "含服", "外用", "用过", "用了",
                "药名", "感冒药", "退烧药", "止痛药", "润喉片",
            )
        )
        if pending_field == "used_medicines" and not mentions_allergy:
            interpretation.allergy_or_contraindication = str(
                existing.get("allergy_or_contraindication") or ""
            ).strip()
        if pending_field == "allergy_or_contraindication" and not mentions_medicine_use:
            interpretation.used_medicines = str(existing.get("used_medicines") or "").strip()

        if cls._is_unknown_safety_answer(interpretation.used_medicines):
            interpretation.used_medicines = "不确定"
        if cls._is_unknown_safety_answer(interpretation.allergy_or_contraindication):
            interpretation.allergy_or_contraindication = "不确定"
        interpretation.duration = (
            interpretation.duration
            or explicit_duration
            or str(existing.get("duration") or "").strip()
        )
        interpretation.used_medicines = (
            interpretation.used_medicines
            or cls.used_medicine_answer(
                transcript,
                allow_short_answer=pending_field == "used_medicines",
            )
            or str(existing.get("used_medicines") or "").strip()
        )
        interpretation.allergy_or_contraindication = (
            interpretation.allergy_or_contraindication
            or cls.allergy_answer(
                transcript,
                allow_short_answer=pending_field == "allergy_or_contraindication",
            )
            or str(existing.get("allergy_or_contraindication") or "").strip()
        )

        # A direct answer to the immediately preceding safety question is more
        # reliable than a model-filled safety field.  In particular, short
        # colloquial replies such as “无” must not be overwritten by a stale or
        # uncertain model value, otherwise the same question is asked again.
        if pending_field == "used_medicines":
            explicit_used_medicines = cls.used_medicine_answer(
                transcript,
                allow_short_answer=True,
            )
            if explicit_used_medicines:
                interpretation.used_medicines = explicit_used_medicines
        elif pending_field == "allergy_or_contraindication":
            explicit_allergy = cls.allergy_answer(
                transcript,
                allow_short_answer=True,
            )
            if explicit_allergy:
                interpretation.allergy_or_contraindication = explicit_allergy

        if explicit_duration:
            interpretation.answered_topics_this_turn = list(
                dict.fromkeys([*interpretation.answered_topics_this_turn, "onset"])
            )
            interpretation.topic_evidence.setdefault("onset", explicit_duration)

        if symptom_scope_explicitly_complete(transcript):
            interpretation.symptom_scope_complete = True
        elif pending_field == "additional_symptoms" and not cls._asks_for_explanation(transcript):
            # The user has answered the one scope question. A positive answer is
            # also complete: any newly stated symptoms are merged before the
            # focused four-question clinical pass begins.
            interpretation.symptom_scope_complete = bool(transcript.strip())

        detected_change, replaced = cls._detect_symptom_change(
            transcript,
            existing,
            interpretation,
        )
        if detected_change == "replace":
            interpretation.material_symptom_change = True
            interpretation.symptom_change_type = "replace"
            interpretation.replaced_concepts = list(
                dict.fromkeys([*interpretation.replaced_concepts, *replaced])
            )[:4]
            interpretation.symptom_scope_complete = False
        elif interpretation.symptom_change_type == "none" and detected_change in {"add", "refine"}:
            interpretation.symptom_change_type = detected_change

    @staticmethod
    def _is_unknown_safety_answer(value: str) -> bool:
        text = str(value or "").strip()
        return bool(
            text
            and any(
                term in text
                for term in (
                    "不确定", "不知道", "不清楚", "不详", "记不清", "无法确认",
                    "不能明确", "说不出药名", "不知道药名", "药名不详",
                )
            )
        )

    @classmethod
    def _pending_answer_field(cls, existing: dict[str, Any]) -> str:
        explicit = str(existing.get("pending_clarification") or "").strip()
        if explicit == "onset":
            return "duration"
        if explicit in {
            "additional_symptoms",
            "used_medicines",
            "allergy_or_contraindication",
        }:
            return explicit
        for message in reversed(existing.get("conversation") or []):
            if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
                continue
            question = re.sub(r"\s+", "", str(message.get("content") or ""))
            if any(term in question for term in ("过敏", "禁忌", "不能使用", "不能用")):
                return "allergy_or_contraindication"
            if any(term in question for term in ("用过药", "用药", "吃过药", "吃药", "服药")):
                return "used_medicines"
            if any(term in question for term in ("持续", "多久", "多长时间")):
                return "duration"
            return ""
        return ""

    @staticmethod
    def _asks_for_explanation(transcript: str) -> bool:
        text = str(transcript or "").strip()
        return any(
            phrase in text
            for phrase in ("什么意思", "什么算", "有哪些", "怎么回答", "没听懂", "为什么要问")
        )

    @classmethod
    def _detect_symptom_change(
        cls,
        transcript: str,
        existing: dict[str, Any],
        interpretation: SymptomInterpretation,
    ) -> tuple[str, list[str]]:
        """Deterministic support for explicit add/refine/replace language.

        The model remains responsible for semantic interpretation. This guard
        only ensures an unmistakable correction cannot retain the old four-
        question budget when the model omits its change flag.
        """
        text = re.sub(r"\s+", "", str(transcript or ""))
        if not text:
            return "none", []
        current_concepts = [
            str(item.get("concept") or "").strip()
            for item in existing.get("observations") or []
            if isinstance(item, dict)
            and str(item.get("status") or "") == "present"
            and str(item.get("concept") or "").strip()
        ]
        symptoms_text = str(existing.get("symptoms_text") or "")
        current_concepts.extend(
            part.strip() for part in symptoms_text.split("、") if part.strip()
        )
        current_concepts = list(dict.fromkeys(current_concepts))
        replaced = [
            concept
            for concept in current_concepts
            if re.search(rf"(?:不是|并不是|不算|说错了不是){re.escape(concept)}", text)
        ]
        explicit_replace = bool(
            replaced
            or "我说错了" in text
            or re.search(r"不是[^，。；]{1,16}(?:而是|其实是|是)[^，。；]{1,16}", text)
        )
        if "都不是" in text and len(current_concepts) == 1:
            replaced = current_concepts[:1]
            explicit_replace = True
        if explicit_replace:
            return "replace", replaced
        if any(marker in text for marker in ("还有", "同时", "另外", "除此之外也")):
            return "add", []
        if any(marker in text for marker in ("更像", "准确说", "具体是", "更准确")):
            return "refine", []
        return "none", []

    @staticmethod
    def _is_contextual_short_answer(transcript: str, pending_field: str) -> bool:
        if pending_field not in {"used_medicines", "allergy_or_contraindication"}:
            return False
        compact = re.sub(r"[\s，。！？,.!?]", "", transcript or "")
        return is_contextual_negative_answer(transcript) or compact in {"不知道", "不清楚", "不确定"}

    @staticmethod
    def _is_generic_opening_question(question: str) -> bool:
        compact = re.sub(r"\s+", "", question or "")
        return any(
            phrase in compact
            for phrase in (
                "哪里不舒服",
                "哪儿不舒服",
                "什么地方不舒服",
                "今天有什么不舒服",
                "现在感觉如何",
                "目前感觉如何",
            )
        )

    @staticmethod
    def _short_text(value: object, limit: int) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

    @staticmethod
    def _bool_value(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

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
