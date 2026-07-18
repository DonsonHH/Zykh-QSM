from __future__ import annotations

from uuid import uuid4

from .. import db
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.inquiry import (
    InquiryExtractedInformation,
    InquirySessionCreateRequest,
    InquirySessionResponse,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from .medicine_safety_engine import MedicineSafetyEngine
from .symptom_interpreter import SymptomInterpretation, SymptomInterpreter


VITALS_DIMENSIONS = {"发热全身不适", "咳嗽咳痰", "恶心暑湿"}


class InquiryOrchestrator:
    def __init__(
        self,
        repository: InquiryRepository | None = None,
        interpreter: SymptomInterpreter | None = None,
        safety_engine: MedicineSafetyEngine | None = None,
    ) -> None:
        self.repository = repository or InquiryRepository()
        self.interpreter = interpreter or SymptomInterpreter()
        self.safety_engine = safety_engine or MedicineSafetyEngine()

    def create_session(self, request: InquirySessionCreateRequest) -> InquirySessionResponse:
        user = self._load_user(request.service_user_id)
        now = db.now_text()
        user_name = str(user.get("name") or request.guest_name.strip() or "访客")
        reply = (
            f"{user_name}，已读取你的基础信息。请告诉我现在最不舒服的地方。"
            if user
            else "本次将以访客身份记录。请告诉我现在最不舒服的地方。"
        )
        session = InquirySessionResponse(
            session_id=f"inquiry-session-{uuid4().hex[:14]}",
            user_id=str(user.get("id") or ""),
            user_name=user_name,
            user_age=int(user.get("age") or 0),
            user_profile=str(user.get("profile") or ""),
            user_allergies=str(user.get("allergies") or ""),
            stage="symptoms",
            reply=reply,
            source="rules_fallback",
            extracted_information=InquiryExtractedInformation(
                allergy_or_contraindication=str(user.get("allergies") or "")
            ),
            next_action="ask",
            title=f"{user_name}的新问询",
            created_at=now,
            updated_at=now,
        )
        self.repository.save_session(session)
        self.repository.append_message(session.session_id, "assistant", reply, "rules_fallback")
        return self._required_session(session.session_id)

    def get_session(self, session_id: str) -> InquirySessionResponse:
        return self._required_session(session_id)

    def process_turn(self, session_id: str, request: InquiryTurnRequest) -> InquirySessionResponse:
        session = self._required_session(session_id)
        transcript = request.transcript.strip()
        self.repository.append_message(session_id, "user", transcript, "speech")

        emergency_extracted = session.extracted_information.model_copy(deep=True)
        emergency_extracted.symptoms_text = self._append_text(emergency_extracted.symptoms_text, transcript)
        emergency = self.safety_engine.assess(emergency_extracted, session.vitals)
        if emergency.risk_level == "emergency":
            session.extracted_information = emergency_extracted
            return self._finish(session, emergency_extracted, source="safety_rules")

        interpretation = self.interpreter.interpret(
            transcript,
            session.extracted_information.model_dump(),
            {
                "name": session.user_name,
                "age": session.user_age,
                "profile": session.user_profile,
                "allergies": session.user_allergies,
            },
        )
        extracted = self._merge_interpretation(session, transcript, interpretation)
        session.extracted_information = extracted
        session.source = interpretation.source

        missing = self._missing_field(extracted)
        if missing:
            stage, reply = self._follow_up(missing, interpretation.follow_up_question)
            session.stage = stage
            session.next_action = "ask"
            session.reply = reply
            session.risk_level = None
            session.risk_reasons = []
            session.primary_candidate = None
            session.alternative_candidate = None
            session.can_view_medicines = False
            return self._commit(session)

        if self._requires_vitals(extracted) and not session.vitals:
            session.stage = "vitals"
            session.next_action = "measure_vitals"
            session.reply = "关键信息已整理。请完成心率、血氧和额温测量，确认后我会继续进行安全核验。"
            return self._commit(session)

        return self._finish(session, extracted, source=interpretation.source)

    def attach_vitals(self, session_id: str, request: InquiryVitalsRequest) -> InquirySessionResponse:
        session = self._required_session(session_id)
        session.vitals = request.model_dump(exclude_none=True)
        return self._finish(session, session.extracted_information, source=session.source)

    def _finish(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        *,
        source: str,
    ) -> InquirySessionResponse:
        decision = self.safety_engine.assess(extracted, session.vitals)
        session.extracted_information = extracted
        session.risk_level = decision.risk_level
        session.risk_reasons = decision.risk_reasons
        session.primary_candidate = decision.primary_candidate
        session.alternative_candidate = decision.alternative_candidate
        session.source = source
        session.can_view_medicines = bool(
            decision.risk_level in {"low", "medium"} and decision.primary_candidate is not None
        )
        session.title = self._title(session)
        if decision.risk_level in {"high", "emergency"}:
            session.stage = "escalated"
            session.next_action = "escalate"
            session.reply = (
                "检测到需要立即处理的危险信号，请停止自行取药并立即联系医生或救援人员。"
                if decision.risk_level == "emergency"
                else "当前存在高风险信号，本次不展示候选药品，请尽快联系医生或现场协助人员。"
            )
        elif decision.primary_candidate is None:
            session.stage = "result"
            session.next_action = "escalate"
            session.reply = "当前库存中没有通过禁忌、有效期和适用信息核验的候选药品，请联系医生或家人协助。"
        else:
            session.stage = "result"
            session.next_action = "show_recommendation"
            alternative = (
                f"另有备选 {decision.alternative_candidate.name}，两者是二选一的信息参考。"
                if decision.alternative_candidate
                else "当前信息较明确，不额外生成备选。"
            )
            session.reply = (
                f"安全核验已完成，可查看主候选 {decision.primary_candidate.name} 的说明与安全提示。"
                f"{alternative}后续仍需在药品页完成原有取药确认。"
            )
        return self._commit(session)

    def _commit(self, session: InquirySessionResponse) -> InquirySessionResponse:
        session.updated_at = db.now_text()
        self.repository.save_session(session)
        self.repository.append_message(session.session_id, "assistant", session.reply, session.source)
        return self._required_session(session.session_id)

    def _required_session(self, session_id: str) -> InquirySessionResponse:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ValueError("问询会话不存在或已结束。")
        return session

    @staticmethod
    def _load_user(user_id: str) -> dict[str, object]:
        if not user_id:
            return {}
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT id, name, age, profile, allergies FROM service_users WHERE id=?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def _merge_interpretation(
        session: InquirySessionResponse,
        transcript: str,
        interpretation: SymptomInterpretation,
    ) -> InquiryExtractedInformation:
        current = session.extracted_information
        dimensions = list(dict.fromkeys([*current.symptom_dimensions, *interpretation.symptom_dimensions]))
        evidence = {**current.dimension_evidence, **interpretation.dimension_evidence}
        return InquiryExtractedInformation(
            symptom_dimensions=dimensions,
            dimension_evidence=evidence,
            symptoms_text=InquiryOrchestrator._append_text(current.symptoms_text, transcript),
            duration=interpretation.duration or current.duration,
            used_medicines=interpretation.used_medicines or current.used_medicines,
            allergy_or_contraindication=(
                interpretation.allergy_or_contraindication
                or current.allergy_or_contraindication
                or session.user_allergies
            ),
            confidence=max(current.confidence, interpretation.confidence),
        )

    @staticmethod
    def _missing_field(extracted: InquiryExtractedInformation) -> str:
        if not extracted.symptom_dimensions:
            return "symptoms"
        if not extracted.duration:
            return "duration"
        if not extracted.used_medicines:
            return "used_medicines"
        if not extracted.allergy_or_contraindication:
            return "allergies"
        return ""

    @staticmethod
    def _follow_up(missing: str, model_question: str) -> tuple[str, str]:
        questions = {
            "symptoms": ("symptoms", "请具体说说现在最不舒服的地方。"),
            "duration": ("duration", "这种不舒服持续多久了？"),
            "used_medicines": ("used_medicines", "这次不舒服以后已经用过什么药吗？"),
            "allergies": ("allergies", "有没有药物过敏或明确不能使用的药？"),
        }
        question_terms = {
            "symptoms": ("不舒服", "症状", "哪里", "感觉", "描述"),
            "duration": ("多久", "多长时间", "几天", "什么时候开始", "持续"),
            "used_medicines": ("用药", "什么药", "吃药", "服药", "使用过"),
            "allergies": ("过敏", "禁忌", "不能用", "不能使用"),
        }
        stage, fallback = questions[missing]
        proposed = model_question.strip()
        question = proposed if proposed and any(term in proposed for term in question_terms[missing]) else fallback
        return stage, question

    @staticmethod
    def _requires_vitals(extracted: InquiryExtractedInformation) -> bool:
        return bool(VITALS_DIMENSIONS.intersection(extracted.symptom_dimensions))

    @staticmethod
    def _append_text(existing: str, value: str) -> str:
        return "；".join(part for part in (existing.strip(), value.strip()) if part)

    @staticmethod
    def _title(session: InquirySessionResponse) -> str:
        evidence = next(iter(session.extracted_information.dimension_evidence.values()), "健康问询")
        return f"{session.user_name} · {evidence[:12]}"
