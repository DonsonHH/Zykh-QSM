from __future__ import annotations

from difflib import SequenceMatcher
import re
import threading
from uuid import uuid4

from .. import db
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.dispense import DispenseConfirmRequest
from ..schemas.inquiry import (
    InquiryExtractedInformation,
    InquiryInformationRevisionRequest,
    InquirySessionCreateRequest,
    InquirySessionResponse,
    InquiryTreatmentConfirmRequest,
    InquiryTreatmentConfirmResponse,
    InquiryTreatmentDispenseItem,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from .dispense_service import DispenseError, DispenseService
from .inquiry_history_service import InquiryHistoryContext, InquiryHistoryService
from .inquiry_guest_archive_service import InquiryGuestArchiveService
from .medicine_safety_engine import MedicineSafetyEngine
from .symptom_interpreter import SymptomInterpretation, SymptomInterpreter


VITALS_DIMENSIONS = {"发热全身不适", "咳嗽咳痰", "恶心暑湿"}
MODEL_LED_SOURCES = {"cloud", "local_llm"}

CLARIFICATION_QUESTIONS = {
    "history_change": "你以前有过相似情况。这次和上次相比，是更重、更轻，还是表现不一样？",
    "nasal_discharge": "鼻部不适更接近哪一种：清稀鼻涕、黄稠鼻涕，还是鼻痒并连续打喷嚏？",
    "systemic_pattern": "除了头痛或发热，现在更明显的是怕冷，还是口渴、咽喉疼痛？",
    "cough_type": "这次主要是干咳，还是咳嗽时有痰？如果有痰，请说一下颜色。",
    "throat_pattern": "口咽不适主要是咽喉疼痛，还是口腔溃疡？",
    "summer_pattern": "头晕或暑热不适时，是否还伴有胸闷腹胀、恶心呕吐或腹泻？",
    "wound_state": "伤口只是轻微破皮，还是已经出现红肿、渗液？",
    "allergy_pattern": "过敏不适主要在鼻部，还是以皮肤瘙痒、皮疹为主？",
}


class InquiryOrchestrator:
    _treatment_action_lock = threading.Lock()

    def __init__(
        self,
        repository: InquiryRepository | None = None,
        interpreter: SymptomInterpreter | None = None,
        safety_engine: MedicineSafetyEngine | None = None,
        dispense_service: DispenseService | None = None,
        history_service: InquiryHistoryService | None = None,
        guest_archive_service: InquiryGuestArchiveService | None = None,
    ) -> None:
        self.repository = repository or InquiryRepository()
        self.interpreter = interpreter or SymptomInterpreter()
        self.safety_engine = safety_engine or MedicineSafetyEngine()
        self.dispense_service = dispense_service or DispenseService()
        self.history_service = history_service or InquiryHistoryService(self.repository)
        self.guest_archive_service = guest_archive_service or InquiryGuestArchiveService()

    def create_session(self, request: InquirySessionCreateRequest) -> InquirySessionResponse:
        user = self._load_user(request.service_user_id)
        now = db.now_text()
        user_name = str(user.get("name") or request.guest_name.strip() or "访客")
        fallback_reply = (
            f"{user_name}，你好。今天哪里不舒服？慢慢说，我会边听边帮你整理。"
            if user
            else "你好。今天哪里不舒服？慢慢说，我会边听边帮你整理。"
        )
        opening = getattr(self.interpreter, "opening_question", None)
        reply, opening_source = (
            opening(
                {
                    "name": user_name,
                    "profile": str(user.get("profile") or ""),
                    "allergies": str(user.get("allergies") or ""),
                },
                fallback_reply,
            )
            if callable(opening)
            else (fallback_reply, "assistant")
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
            source=opening_source,
            extracted_information=InquiryExtractedInformation(
                allergy_or_contraindication=str(user.get("allergies") or "")
            ),
            next_action="ask",
            title=f"{user_name}的新问询",
            created_at=now,
            updated_at=now,
        )
        self.repository.save_session(session)
        self.repository.append_message(session.session_id, "assistant", reply, opening_source)
        if not user:
            self.guest_archive_service.schedule_capture(session.session_id, user_name)
        return self._required_session(session.session_id)

    def get_session(self, session_id: str) -> InquirySessionResponse:
        return self._required_session(session_id)

    def process_turn(self, session_id: str, request: InquiryTurnRequest) -> InquirySessionResponse:
        session = self._required_session(session_id)
        transcript = request.transcript.strip().rstrip("。．.").strip()
        self.repository.append_message(session_id, "user", transcript, "speech")

        emergency_extracted = session.extracted_information.model_copy(deep=True)
        emergency_extracted.symptoms_text = self._append_text(emergency_extracted.symptoms_text, transcript)
        emergency = self.safety_engine.assess(
            emergency_extracted,
            session.vitals,
            self._profile_context(session),
        )
        if emergency.risk_level in {"high", "emergency"}:
            session.extracted_information = emergency_extracted
            return self._finish(session, emergency_extracted, source="safety_rules")

        existing_context = session.extracted_information.model_dump()
        existing_context["current_stage"] = session.stage
        existing_context["conversation_turns"] = self._current_user_turn_count(session)
        existing_context["conversation"] = [
            {"role": message.role, "content": message.content}
            for message in session.messages
        ]
        interpretation = self.interpreter.interpret(
            transcript,
            existing_context,
            {
                "name": session.user_name,
                "age": session.user_age,
                "profile": session.user_profile,
                "allergies": session.user_allergies,
            },
        )
        self._apply_contextual_answer(session.stage, transcript, interpretation)
        extracted = self._merge_interpretation(session, transcript, interpretation)
        session.extracted_information = extracted
        session.source = interpretation.source
        session.reasoning_summary = interpretation.reasoning_summary
        session.model_action_intent = interpretation.action_intent
        session.action_reason = interpretation.action_reason
        model_led = interpretation.source in MODEL_LED_SOURCES
        if model_led and extracted.pending_clarification:
            extracted.pending_clarification = ""
            session.extracted_information = extracted

        if not session.vitals and self._should_measure_vitals_now(
            transcript,
            extracted,
            interpretation,
            model_led=model_led,
        ):
            session.stage = "vitals"
            session.next_action = "measure_vitals"
            session.reply = "这项信息现在会影响安全判断。请测量额温、心率和血氧，完成后我会接着询问尚未确认的内容。"
            self._clear_decision(session)
            return self._commit(session)

        history = self._history_context(session, extracted)
        if model_led:
            missing = self._missing_field(extracted)
            if interpretation.follow_up_question and (
                missing
                or interpretation.action_intent == "ask"
            ):
                if self._repeats_answered_question(session, interpretation):
                    if missing:
                        self._ask_for_missing(session, missing, "")
                        return self._commit(session)
                    return self._finish(session, extracted, source=interpretation.source)
                self._ask_model_followup(
                    session,
                    interpretation.assistant_reply,
                    interpretation.follow_up_question,
                    missing,
                )
                return self._commit(session)
            if missing:
                self._ask_for_missing(session, missing, "")
                return self._commit(session)
            if self._requires_vitals(extracted, interpretation) and not session.vitals:
                session.stage = "vitals"
                session.next_action = "measure_vitals"
                session.reply = "为了确认当前状态，请测量额温、心率和血氧。完成后我会接着整理结果。"
                return self._commit(session)
            return self._finish(session, extracted, source=interpretation.source)

        if extracted.pending_clarification:
            self._repeat_pending_clarification(session, extracted.pending_clarification)
            return self._commit(session)
        clarification = self._next_clarification(extracted, history)
        if clarification:
            self._ask_clarification(session, *clarification)
            return self._commit(session)

        missing = self._missing_field(extracted)
        if missing:
            self._ask_for_missing(session, missing, interpretation.follow_up_question)
            return self._commit(session)

        if self._requires_vitals(extracted, interpretation) and not session.vitals:
            session.stage = "vitals"
            session.next_action = "measure_vitals"
            session.reply = "为了让安全判断更准确，接下来测一下额温、心率和血氧。完成后会自动回到这里继续。"
            return self._commit(session)

        return self._finish(session, extracted, source=interpretation.source)

    def attach_vitals(self, session_id: str, request: InquiryVitalsRequest) -> InquirySessionResponse:
        session = self._required_session(session_id)
        session.vitals = request.model_dump(exclude_none=True)
        history = self._history_context(session, session.extracted_information)
        immediate = self.safety_engine.assess(
            session.extracted_information,
            session.vitals,
            self._profile_context(session),
            history.medicine_counts,
        )
        if immediate.risk_level in {"high", "emergency"}:
            return self._finish(session, session.extracted_information, source="safety_rules")
        if session.source not in MODEL_LED_SOURCES:
            clarification = self._next_clarification(session.extracted_information, history)
            if clarification:
                self._ask_clarification(session, *clarification)
                return self._commit(session)
        missing = self._missing_field(session.extracted_information)
        if missing:
            self._ask_for_missing(session, missing, "")
            return self._commit(session)
        return self._finish(session, session.extracted_information, source=session.source)

    def revise_information(
        self,
        session_id: str,
        request: InquiryInformationRevisionRequest,
    ) -> InquirySessionResponse:
        """Replace reviewed facts as one coherent state update before showing a result."""
        session = self._required_session(session_id)
        complaint = request.main_complaint.strip().rstrip("。．.").strip()
        duration = request.duration.strip()
        used_medicines = request.used_medicines.strip()
        allergy = request.allergy_or_contraindication.strip()
        interpretation = self.interpreter.interpret(
            complaint,
            {
                "duration": duration,
                "used_medicines": used_medicines,
                "allergy_or_contraindication": allergy,
                "current_stage": "review",
            },
            {
                "name": session.user_name,
                "age": session.user_age,
                "profile": session.user_profile,
                "allergies": session.user_allergies,
            },
        )
        extracted = InquiryExtractedInformation(
            symptom_dimensions=interpretation.symptom_dimensions,
            dimension_evidence=interpretation.dimension_evidence,
            symptom_features=interpretation.symptom_features,
            feature_evidence=interpretation.feature_evidence,
            symptoms_text=complaint,
            duration=duration,
            used_medicines=used_medicines,
            allergy_or_contraindication=allergy,
            confidence=interpretation.confidence,
        )
        session.extracted_information = extracted
        session.source = interpretation.source
        session.reasoning_summary = (
            interpretation.reasoning_summary
            or "已根据核对后的主诉、持续时间、用药和禁忌信息重新整理。"
        )
        session.model_action_intent = "analyze"
        session.action_reason = "用户已在信息核对页确认或修正本次情况"
        self._clear_decision(session)

        if not request.finalize:
            missing = self._missing_field(extracted)
            if missing:
                self._ask_for_missing(session, missing, "")
                return self._commit(session)
            if self._requires_vitals(extracted, interpretation) and not session.vitals:
                session.stage = "vitals"
                session.next_action = "measure_vitals"
                session.reply = "修正内容已保存。为了完成安全核验，请测量额温、心率和血氧。"
                return self._commit(session)

        return self._finish(session, extracted, source=interpretation.source)

    def confirm_treatment(
        self,
        session_id: str,
        request: InquiryTreatmentConfirmRequest,
    ) -> InquiryTreatmentConfirmResponse:
        if request.confirmed_safety_notice is not True:
            raise DispenseError("请先核对并确认本次方案和安全提示。")

        with self._treatment_action_lock:
            session = self._required_session(session_id)
            if session.action_status not in {"ready", "opening"}:
                raise DispenseError("本次方案已经处理或当前不可执行，请重新开始问询。", status_code=409)
            if session.risk_level not in {"low", "medium"} or not session.can_view_medicines:
                raise DispenseError("当前风险等级不允许执行开柜操作。", status_code=409)

            if session.action_status == "opening" and session.selected_option_id != request.option_id:
                raise DispenseError("已有方案正在执行，不能切换到其他方案。", status_code=409)

            displayed_option = self._option(session.treatment_options, request.option_id)
            if displayed_option is None:
                raise DispenseError("未找到所选方案，请重新选择。")

            history = self._history_context(session, session.extracted_information)
            decision = self.safety_engine.assess(
                session.extracted_information,
                session.vitals,
                self._profile_context(session),
                history.medicine_counts,
            )
            if decision.risk_level not in {"low", "medium"}:
                self._replace_with_fresh_decision(session, decision)
                self._commit(session)
                raise DispenseError("安全状态已经变化，本次不再执行开柜。", status_code=409)

            fresh_option = self._option(decision.treatment_options, request.option_id)
            if fresh_option is None or self._option_medicine_ids(fresh_option) != self._option_medicine_ids(displayed_option):
                self._replace_with_fresh_decision(session, decision)
                self._commit(session)
                raise DispenseError("库存或安全信息已经变化，请重新核对方案。", status_code=409)

            expected = len(fresh_option.medicines)
            if expected <= 0:
                raise DispenseError("所选方案没有可执行药品。", status_code=409)
            if session.action_status == "ready":
                if request.expected_item_index != 0:
                    raise DispenseError("开柜进度已经失效，请重新核对方案。", status_code=409)
                session.selected_option_id = request.option_id
                session.action_progress_index = 0
                session.action_total_items = expected
                session.action_items = []
            if request.expected_item_index != session.action_progress_index:
                raise DispenseError("开柜进度已经更新，请刷新后继续。", status_code=409)
            if session.action_progress_index >= expected:
                raise DispenseError("本方案对应药柜已经全部处理。", status_code=409)

            item_index = session.action_progress_index
            treatment_medicine = fresh_option.medicines[item_index]
            session.action_status = "opening"
            session.action_total_items = expected
            session.action_message = f"正在打开第 {item_index + 1}/{expected} 个药柜：{treatment_medicine.slot}号柜。"
            session.reply = session.action_message
            self._commit(session)

            medicine = self.safety_engine.knowledge.medicine_repository.get_by_id(treatment_medicine.id)
            item: InquiryTreatmentDispenseItem
            if medicine is None:
                item = InquiryTreatmentDispenseItem(
                    medicine_id=treatment_medicine.id,
                    medicine_name=treatment_medicine.name,
                    slot=treatment_medicine.slot,
                    ok=False,
                    dry_run=False,
                    message="药品库存记录已经变化。",
                )
            else:
                try:
                    result = self.dispense_service.confirm(
                        DispenseConfirmRequest(
                            medicine_id=medicine.id,
                            slot=medicine.slot,
                            quantity=1,
                            reason=(
                                f"AI应急问询 {session.session_id} 方案 {request.option_id} "
                                f"第{item_index + 1}/{expected}柜"
                            ),
                            confirmed_safety_notice=True,
                            confirm_real_dispense=True,
                            target_user_id=session.user_id,
                            target_user_name=session.user_name,
                            verification_method="inquiry_confirmed",
                        )
                    )
                    item = InquiryTreatmentDispenseItem(
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                        slot=medicine.slot,
                        ok=result.ok,
                        dry_run=result.dry_run,
                        message=result.message,
                        record_id=result.record_id,
                    )
                except DispenseError as exc:
                    item = InquiryTreatmentDispenseItem(
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                        slot=medicine.slot,
                        ok=False,
                        dry_run=False,
                        message=exc.message,
                    )

            session.action_items = [*session.action_items, item.model_dump()]
            if item.ok:
                session.action_progress_index += 1

            if not item.ok:
                status = "partial" if session.action_progress_index > 0 else "failed"
                message = (
                    f"已处理 {session.action_progress_index}/{expected} 个药柜，"
                    f"{treatment_medicine.slot}号柜未完成：{item.message}"
                )
                ok = False
            elif session.action_progress_index >= expected:
                status = "complete"
                opened = sum(
                    1 for value in session.action_items if value.get("ok") and not value.get("dry_run")
                )
                message = (
                    f"方案 {request.option_id} 的 {opened} 个药柜已按顺序完成开柜。"
                    if opened
                    else f"方案 {request.option_id} 的 {expected} 项本地测试记录已完成。"
                )
                ok = True
            else:
                status = "opening"
                next_item = fresh_option.medicines[session.action_progress_index]
                message = (
                    f"已打开 {item_index + 1}/{expected}：{treatment_medicine.slot}号柜；"
                    f"下一步打开 {next_item.slot}号柜。"
                )
                ok = True

            session.action_status = status
            session.action_message = message
            session.reply = message
            session.next_action = "complete" if status in {"complete", "partial", "failed"} else "show_recommendation"
            committed = self._commit(session)
            next_medicine = (
                fresh_option.medicines[session.action_progress_index]
                if status == "opening" and session.action_progress_index < expected
                else None
            )
            return InquiryTreatmentConfirmResponse(
                ok=ok,
                status=status,
                option_id=request.option_id,
                message=message,
                items=[InquiryTreatmentDispenseItem(**value) for value in session.action_items],
                completed_count=session.action_progress_index,
                total_count=expected,
                next_medicine=next_medicine,
                session=committed,
            )

    def _finish(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        *,
        source: str,
    ) -> InquirySessionResponse:
        history = self._history_context(session, extracted)
        decision = self.safety_engine.assess(
            extracted,
            session.vitals,
            self._profile_context(session),
            history.medicine_counts,
        )
        session.extracted_information = extracted
        session.risk_level = decision.risk_level
        session.risk_reasons = decision.risk_reasons
        session.primary_candidate = decision.primary_candidate
        session.alternative_candidate = decision.alternative_candidate
        session.treatment_options = decision.treatment_options
        session.source = source
        session.can_view_medicines = bool(
            decision.risk_level in {"low", "medium"} and bool(decision.treatment_options)
        )
        session.selected_option_id = ""
        session.action_status = "ready" if session.can_view_medicines else "idle"
        session.action_message = ""
        session.action_progress_index = 0
        session.action_total_items = 0
        session.action_items = []
        if history.has_similar_history:
            history_note = f"已参考 {history.similar_session_count} 次相似历史，仅用于当前合格候选的排序。"
            session.reasoning_summary = "".join(
                part for part in (session.reasoning_summary, history_note) if part
            )
        self._apply_recommendation_language(session, decision)
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
            option_count = len(decision.treatment_options)
            option_text = (
                f"结合这些信息，我整理了 {option_count} 个不同侧重点的选择，你可以对照原因和用法选一项。"
                if option_count > 1
                else "结合这些信息，我整理了一个更贴近当前情况的选择。"
            )
            natural_summary = self._natural_summary(session.reasoning_summary)
            session.reply = f"{natural_summary}{option_text}"
        return self._commit(session)

    def _apply_recommendation_language(self, session: InquirySessionResponse, decision) -> None:
        if decision.risk_level not in {"low", "medium"} or not decision.treatment_options:
            return
        context = {
            "user_name": session.user_name,
            "reasoning_summary": session.reasoning_summary,
            "symptom_dimensions": session.extracted_information.symptom_dimensions,
            "symptom_evidence": session.extracted_information.dimension_evidence,
            "duration": session.extracted_information.duration,
            "used_medicines": session.extracted_information.used_medicines,
            "allergy_or_contraindication": session.extracted_information.allergy_or_contraindication,
            "vitals": session.vitals or {},
            "risk_level": decision.risk_level,
            "options": [
                {
                    "option_id": option.option_id,
                    "medicines": [
                        {
                            "name": medicine.name,
                            "indications": medicine.indications,
                            "dosage": medicine.dosage,
                            "role": medicine.role,
                            "covered_symptoms": medicine.covered_symptoms,
                        }
                        for medicine in option.medicines
                    ],
                }
                for option in decision.treatment_options
            ],
        }
        narrator = getattr(self.interpreter, "explain_recommendation", None)
        language = narrator(context) if callable(narrator) else {"ok": False}
        if not language.get("ok"):
            return
        summary = str(language.get("summary") or "").strip()
        if summary:
            session.reasoning_summary = summary
        reasons = language.get("option_reasons")
        reasons = reasons if isinstance(reasons, dict) else {}
        for option in decision.treatment_options:
            reason = str(reasons.get(option.option_id) or "").strip()
            if reason:
                option.when = reason[:120]

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
        features = list(dict.fromkeys([*current.symptom_features, *interpretation.symptom_features]))
        feature_evidence = {
            **current.feature_evidence,
            **interpretation.feature_evidence,
        }
        clarification_answers = dict(current.clarification_answers)
        pending_clarification = current.pending_clarification
        if pending_clarification:
            contextual_features = InquiryOrchestrator._clarification_features(pending_clarification, transcript)
            if InquiryOrchestrator._valid_clarification_answer(
                pending_clarification,
                transcript,
                contextual_features,
            ):
                clarification_answers[pending_clarification] = transcript[:160]
                pending_clarification = ""
            features = list(dict.fromkeys([*features, *contextual_features]))
            for feature in contextual_features:
                feature_evidence[feature] = transcript[:120]
        return InquiryExtractedInformation(
            symptom_dimensions=dimensions,
            dimension_evidence=evidence,
            symptom_features=features,
            feature_evidence=feature_evidence,
            clarification_answers=clarification_answers,
            asked_clarifications=list(current.asked_clarifications),
            pending_clarification=pending_clarification,
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
            "symptoms": ("symptoms", "先说说现在最难受的感觉，比如头痛、头晕、咳嗽或胃不舒服。"),
            "duration": ("duration", "这种不舒服大概从什么时候开始，是刚开始还是已经持续一段时间了？"),
            "used_medicines": ("used_medicines", "这次不舒服以后，有没有吃过或用过药？直接说“没有”也可以。"),
            "allergies": ("allergies", "有没有明确不能用或会过敏的药？没有就直接说“没有”。"),
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

    @classmethod
    def _ask_for_missing(
        cls,
        session: InquirySessionResponse,
        missing: str,
        model_question: str,
    ) -> None:
        stage, reply = cls._follow_up(missing, model_question)
        prior_replies = {message.content for message in session.messages if message.role == "assistant"}
        if reply in prior_replies:
            alternatives = {
                "symptoms": (
                    "我还没有听清最明显的不适，请直接说头痛、胃痛、咳嗽或其他部位。",
                    "请只说现在最难受的一项，我会接着往下问。",
                ),
                "duration": (
                    "我还没听清开始时间，请说刚开始、半天、一天以上，或直接说不确定。",
                    "请告诉我大约从哪一天或哪个时间开始，不清楚也可以直接说。",
                ),
                "used_medicines": (
                    "我还没确认本次用药，请回答未用药、已用药或不确定。",
                    "请只说这次不舒服后是否用过药；不记得也可以直接说。",
                ),
                "allergies": (
                    "我还没确认过敏禁忌，请回答无、有或不确定。",
                    "请说出不能使用的药名；如果记不清，请直接说不确定。",
                ),
            }[missing]
            reply = next((value for value in alternatives if value not in prior_replies), alternatives[-1])
        session.stage = stage
        session.next_action = "ask"
        session.reply = reply
        cls._clear_decision(session)

    @classmethod
    def _ask_clarification(cls, session: InquirySessionResponse, topic: str, question: str) -> None:
        extracted = session.extracted_information.model_copy(deep=True)
        extracted.pending_clarification = topic
        extracted.asked_clarifications = list(dict.fromkeys([*extracted.asked_clarifications, topic]))
        session.extracted_information = extracted
        session.stage = "clarification"
        session.next_action = "ask"
        session.reply = question
        cls._clear_decision(session)

    @classmethod
    def _ask_model_followup(
        cls,
        session: InquirySessionResponse,
        assistant_reply: str,
        question: str,
        missing: str,
    ) -> None:
        session.stage = cls._question_stage(question, missing)
        session.next_action = "ask"
        session.reply = assistant_reply.strip() or question.strip()
        cls._clear_decision(session)

    @classmethod
    def _repeats_answered_question(
        cls,
        session: InquirySessionResponse,
        interpretation: SymptomInterpretation,
    ) -> bool:
        candidate = cls._question_signature(
            interpretation.follow_up_question or interpretation.assistant_reply
        )
        if len(candidate) < 4:
            return False
        prior_questions = [
            cls._question_signature(message.content)
            for message in session.messages
            if message.role == "assistant" and ("?" in message.content or "？" in message.content)
        ]
        return any(
            prior and (
                candidate == prior
                or candidate in prior
                or prior in candidate
                or SequenceMatcher(None, candidate, prior).ratio() >= 0.72
            )
            for prior in prior_questions
        )

    @staticmethod
    def _question_signature(value: str) -> str:
        text = str(value or "").strip()
        question_parts = [part for part in re.split(r"[。！？!?]", text) if part.strip()]
        if question_parts:
            text = question_parts[-1]
        text = re.sub(r"^(?:好的|明白了|我记下了|谢谢你说明|请问|那|那么|再确认一下)[，,：:\s]*", "", text)
        text = re.sub(r"(?:请问|现在|目前|这次|一下|呢|吗|呀|啊)", "", text)
        return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text)

    @staticmethod
    def _question_stage(question: str, missing: str) -> str:
        text = question.strip()
        if any(term in text for term in ("多久", "多长时间", "什么时候", "持续", "开始")):
            return "duration"
        if any(term in text for term in ("吃过药", "用过药", "用药", "服药", "什么药")):
            return "used_medicines"
        if any(term in text for term in ("过敏", "禁忌", "不能用", "不能使用")):
            return "allergies"
        if missing in {"symptoms", "duration", "used_medicines", "allergies"}:
            return missing
        return "clarification"

    @classmethod
    def _repeat_pending_clarification(cls, session: InquirySessionResponse, topic: str) -> None:
        session.stage = "clarification"
        session.next_action = "ask"
        session.reply = f"刚才这句我没听清。{CLARIFICATION_QUESTIONS.get(topic, '请换一种说法再告诉我。')}"
        cls._clear_decision(session)

    @staticmethod
    def _next_clarification(
        extracted: InquiryExtractedInformation,
        history: InquiryHistoryContext,
    ) -> tuple[str, str] | None:
        if extracted.pending_clarification:
            return None
        asked = set(extracted.asked_clarifications)
        dimensions = set(extracted.symptom_dimensions)
        features = set(extracted.symptom_features)
        if history.has_similar_history and "history_change" not in asked:
            return "history_change", CLARIFICATION_QUESTIONS["history_change"]
        rules = (
            ("nasal_discharge", "感冒鼻部症状" in dimensions, {"清稀鼻涕", "黄稠鼻涕", "鼻痒喷嚏"}),
            (
                "systemic_pattern",
                "发热全身不适" in dimensions,
                {"明显畏寒", "明显口渴", "咽喉疼痛"},
            ),
            ("cough_type", "咳嗽咳痰" in dimensions, {"干咳", "有痰咳嗽", "黄痰"}),
            ("throat_pattern", "咽喉口腔不适" in dimensions, {"咽喉疼痛", "口腔溃疡"}),
            ("summer_pattern", "恶心暑湿" in dimensions, {"恶心呕吐", "腹泻"}),
            ("wound_state", "轻微外伤" in dimensions, {"皮肤破损", "伤口红肿渗液"}),
            (
                "allergy_pattern",
                bool({"过敏瘙痒", "鼻炎过敏"}.intersection(dimensions)),
                {"鼻痒喷嚏", "皮肤瘙痒"},
            ),
        )
        for topic, applies, resolved_features in rules:
            if applies and topic not in asked and not features.intersection(resolved_features):
                return topic, CLARIFICATION_QUESTIONS[topic]
        return None

    @staticmethod
    def _clarification_features(topic: str, transcript: str) -> list[str]:
        text = transcript.strip()
        matches: list[str] = []

        def has(*terms: str) -> bool:
            return any(SymptomInterpreter._has_unnegated_term(text, term) for term in terms)

        if topic == "nasal_discharge":
            if has("黄", "黄稠", "黏稠"):
                matches.append("黄稠鼻涕")
            elif has("清", "清稀", "清水", "像水"):
                matches.append("清稀鼻涕")
            if has("鼻痒", "打喷嚏", "喷嚏"):
                matches.append("鼻痒喷嚏")
        elif topic == "systemic_pattern":
            if has("怕冷", "畏寒", "恶寒"):
                matches.append("明显畏寒")
            if has("口渴", "口干"):
                matches.append("明显口渴")
            if has("咽痛", "喉咙痛", "嗓子痛"):
                matches.append("咽喉疼痛")
        elif topic == "cough_type":
            if has("黄痰", "痰黄"):
                matches.extend(["有痰咳嗽", "黄痰"])
            elif has("有痰", "咳痰"):
                matches.append("有痰咳嗽")
            elif has("干咳", "无痰", "没有痰"):
                matches.append("干咳")
        elif topic == "throat_pattern":
            if has("口腔溃疡", "嘴里溃疡"):
                matches.append("口腔溃疡")
            if has("咽痛", "喉咙痛", "嗓子痛"):
                matches.append("咽喉疼痛")
        elif topic == "summer_pattern":
            if has("恶心", "呕吐", "想吐"):
                matches.append("恶心呕吐")
            if has("腹泻", "拉肚子", "水样便"):
                matches.append("腹泻")
        elif topic == "wound_state":
            if has("红肿", "渗液", "化脓", "流脓"):
                matches.append("伤口红肿渗液")
            elif has("破皮", "擦破", "小伤口"):
                matches.append("皮肤破损")
        elif topic == "allergy_pattern":
            if has("鼻痒", "打喷嚏", "鼻部"):
                matches.append("鼻痒喷嚏")
            if has("皮肤痒", "瘙痒", "皮疹"):
                matches.append("皮肤瘙痒")
        return list(dict.fromkeys(matches))

    @staticmethod
    def _valid_clarification_answer(topic: str, transcript: str, features: list[str]) -> bool:
        text = transcript.strip()
        if features:
            return True
        if any(term in text for term in ("不清楚", "不知道", "说不清", "不确定", "都没有", "没有这些", "都不是")):
            return True
        if topic == "history_change":
            return any(term in text for term in ("更重", "重一些", "更轻", "轻一些", "一样", "差不多", "不同", "不一样", "没变化"))
        if topic == "wound_state":
            return any(term in text for term in ("只是", "轻微", "破皮", "没红肿", "没有红肿"))
        return False

    @staticmethod
    def _clear_decision(session: InquirySessionResponse) -> None:
        session.risk_level = None
        session.risk_reasons = []
        session.primary_candidate = None
        session.alternative_candidate = None
        session.treatment_options = []
        session.can_view_medicines = False
        session.selected_option_id = ""
        session.action_status = "idle"
        session.action_message = ""
        session.action_progress_index = 0
        session.action_total_items = 0
        session.action_items = []

    @staticmethod
    def _apply_contextual_answer(
        stage: str,
        transcript: str,
        interpretation: SymptomInterpretation,
    ) -> None:
        if stage == "duration" and not interpretation.duration:
            interpretation.duration = SymptomInterpreter.duration_answer(transcript)
        elif stage == "used_medicines" and not interpretation.used_medicines:
            interpretation.used_medicines = SymptomInterpreter.used_medicine_answer(
                transcript,
                allow_short_answer=True,
            )
        elif stage == "allergies" and not interpretation.allergy_or_contraindication:
            interpretation.allergy_or_contraindication = SymptomInterpreter.allergy_answer(
                transcript,
                allow_short_answer=True,
            )

    @staticmethod
    def _requires_vitals(
        extracted: InquiryExtractedInformation,
        interpretation: SymptomInterpretation,
    ) -> bool:
        return bool(
            VITALS_DIMENSIONS.intersection(extracted.symptom_dimensions)
            or interpretation.action_intent == "measure_vitals"
        )

    @classmethod
    def _should_measure_vitals_now(
        cls,
        transcript: str,
        extracted: InquiryExtractedInformation,
        interpretation: SymptomInterpretation,
        *,
        model_led: bool = False,
    ) -> bool:
        explicit_request = any(
            term in transcript
            for term in ("测体征", "测一下体征", "测量体征", "读取体征", "身体体征", "量一下体温")
        )
        if explicit_request:
            return True
        if model_led:
            return interpretation.action_intent == "measure_vitals"
        return cls._requires_vitals(extracted, interpretation)

    @staticmethod
    def _profile_context(session: InquirySessionResponse) -> str:
        return "；".join(
            value.strip()
            for value in (session.user_profile, session.user_allergies)
            if value and value.strip()
        )

    @staticmethod
    def _current_user_turn_count(session: InquirySessionResponse) -> int:
        # The current transcript is persisted before this in-memory session is refreshed.
        return sum(1 for message in session.messages if message.role == "user") + 1

    def _history_context(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
    ) -> InquiryHistoryContext:
        return self.history_service.context_for(
            session.user_id,
            session.session_id,
            extracted.symptom_dimensions,
        )

    @staticmethod
    def _option(options, option_id: str):
        return next((option for option in options if option.option_id == option_id), None)

    @staticmethod
    def _option_medicine_ids(option) -> tuple[str, ...]:
        return tuple(medicine.id for medicine in option.medicines)

    @staticmethod
    def _replace_with_fresh_decision(session: InquirySessionResponse, decision) -> None:
        session.risk_level = decision.risk_level
        session.risk_reasons = decision.risk_reasons
        session.primary_candidate = decision.primary_candidate
        session.alternative_candidate = decision.alternative_candidate
        session.treatment_options = decision.treatment_options
        session.can_view_medicines = bool(
            decision.risk_level in {"low", "medium"} and decision.treatment_options
        )
        session.selected_option_id = ""
        session.action_status = "ready" if session.can_view_medicines else "idle"
        session.action_progress_index = 0
        session.action_total_items = 0
        session.action_items = []
        if decision.risk_level in {"high", "emergency"}:
            session.stage = "escalated"
            session.next_action = "escalate"
            session.action_message = "安全状态已经变化，本次不再执行开柜。"
        elif session.can_view_medicines:
            session.stage = "result"
            session.next_action = "show_recommendation"
            session.action_message = "安全信息已更新，请重新核对方案。"
        else:
            session.stage = "result"
            session.next_action = "escalate"
            session.action_message = "当前没有通过即时核验的候选方案。"
        session.reply = session.action_message

    @staticmethod
    def _append_text(existing: str, value: str) -> str:
        return "；".join(part for part in (existing.strip(), value.strip()) if part)

    @staticmethod
    def _title(session: InquirySessionResponse) -> str:
        evidence = next(iter(session.extracted_information.dimension_evidence.values()), "健康问询")
        return f"{session.user_name} · {evidence[:12]}"

    @staticmethod
    def _natural_summary(value: str) -> str:
        summary = value.strip()
        if not summary:
            return "我已经把你刚才说的情况整理好了。"
        summary = summary.replace("用户", "你").replace("患者", "你")
        summary = summary.rstrip("。！？!?")
        return f"{summary}。"
