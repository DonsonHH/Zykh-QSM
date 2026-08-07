from __future__ import annotations

import re
import threading
from uuid import uuid4

from .. import db
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.dispense import DispenseConfirmRequest
from ..schemas.inquiry import (
    InquiryClinicalAssessment,
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
from .inquiry_dialogue_policy import (
    explicit_topic_evidence,
    MAX_SYMPTOM_FOLLOWUPS,
    SYMPTOM_QUESTION_TOPICS,
    focused_followup_question,
    medication_question_window,
    minimum_clinical_information_ready,
    normalize_answered_topics,
    normalize_topic_evidence,
    symptom_scope_confirmation_question,
)
from .medicine_safety_engine import MedicineSafetyEngine
from .spoken_answer import is_contextual_negative_answer
from .symptom_interpreter import SymptomInterpretation, SymptomInterpreter


class InquiryOrchestrator:
    _treatment_action_lock = threading.Lock()
    _MAX_SYMPTOM_FOLLOWUPS = MAX_SYMPTOM_FOLLOWUPS

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
        user_profile = self._profile_with_note(user)
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
                    "profile": user_profile,
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
            user_profile=user_profile,
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
        emergency = self.safety_engine.assess_guardrails(
            emergency_extracted,
            session.vitals,
        )
        if emergency.risk_level in {"high", "emergency"}:
            session.extracted_information = emergency_extracted
            return self._finish(
                session,
                emergency_extracted,
                source="safety_rules",
                forced_guard=emergency,
            )

        if self._ranking_retry_pending(session) and self._is_ranking_retry_request(transcript):
            # A retry contains no new clinical evidence. Re-run only the
            # inventory-backed ranking step and keep the existing session,
            # instead of feeding the command back through symptom extraction.
            return self._finish(
                session,
                session.extracted_information.model_copy(deep=True),
                source=session.source,
            )

        # The current utterance is passed separately to the model. The in-memory
        # session predates append_message(), so keeping it out of conversation
        # avoids presenting the same sentence twice.
        existing_context = self._model_context(session)
        interpretation = self.interpreter.interpret(
            transcript,
            existing_context,
            self._model_profile(session),
        )
        self._promote_material_symptom_addition(
            session.extracted_information,
            interpretation,
        )
        extracted = self._merge_interpretation(session, transcript, interpretation)
        session.extracted_information = extracted
        session.source = interpretation.source
        session.reasoning_summary = interpretation.reasoning_summary
        session.model_action_intent = interpretation.action_intent
        session.action_reason = interpretation.action_reason
        return self._advance_from_interpretation(
            session,
            extracted,
            interpretation,
            current_transcript=transcript,
        )

    def attach_vitals(self, session_id: str, request: InquiryVitalsRequest) -> InquirySessionResponse:
        self._require_current_real_vitals(request)
        session = self._required_session(session_id)
        session.vitals = request.model_dump(exclude_none=True)
        self.repository.append_message(
            session_id,
            "system",
            self._vitals_event_message(session.vitals),
            "vitals_tool",
        )
        if request.status == "complete":
            immediate = self.safety_engine.assess_guardrails(
                session.extracted_information,
                session.vitals,
            )
            if immediate.risk_level in {"high", "emergency"}:
                return self._finish(
                    session,
                    session.extracted_information,
                    source="safety_rules",
                    forced_guard=immediate,
                )
        existing = self._model_context(session)
        existing["vitals"] = session.vitals
        existing["vitals_event"] = self._vitals_event_message(session.vitals)
        resume = getattr(self.interpreter, "resume_after_vitals", None)
        interpretation = (
            resume(existing, self._model_profile(session))
            if callable(resume)
            else self.interpreter.interpret(
                "体征测量已经完成，请结合本次结果继续问询。",
                existing,
                self._model_profile(session),
            )
        )
        extracted = self._merge_interpretation(session, "", interpretation)
        session.extracted_information = extracted
        session.source = interpretation.source
        session.reasoning_summary = interpretation.reasoning_summary or extracted.case_summary
        session.model_action_intent = interpretation.action_intent
        session.action_reason = interpretation.action_reason
        return self._advance_from_interpretation(session, extracted, interpretation)

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
                **session.extracted_information.model_dump(),
                "duration": duration,
                "used_medicines": used_medicines,
                "allergy_or_contraindication": allergy,
                "current_stage": "review",
                "conversation_turns": self._current_user_turn_count(session),
                "conversation": [
                    {"role": message.role, "content": message.content}
                    for message in session.messages
                ],
                "recent_history": self._history_context(session).model_context(),
                "vitals": session.vitals or {},
            },
            self._model_profile(session),
        )
        extracted = InquiryExtractedInformation(
            case_summary=interpretation.case_summary,
            observations=interpretation.observations,
            uncertainties=interpretation.uncertainties,
            history_relationship=interpretation.history_relationship,
            ai_risk_level=interpretation.ai_risk_level,
            ai_risk_reasons=interpretation.risk_signals,
            ai_available=interpretation.available,
            symptom_dimensions=interpretation.symptom_dimensions,
            dimension_evidence=interpretation.dimension_evidence,
            symptom_features=interpretation.symptom_features,
            feature_evidence=interpretation.feature_evidence,
            symptoms_text=complaint,
            duration=duration,
            symptom_scope_confirmed=True,
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
        session.model_action_intent = interpretation.action_intent
        session.action_reason = interpretation.action_reason or "用户已核对本次信息"
        self._clear_decision(session)

        if not request.finalize:
            return self._advance_from_interpretation(session, extracted, interpretation)
        return self._advance_from_interpretation(session, extracted, interpretation)

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

            guard = self.safety_engine.assess_guardrails(
                session.extracted_information,
                session.vitals,
                ai_risk_level=session.extracted_information.ai_risk_level,
                ai_risk_reasons=session.extracted_information.ai_risk_reasons,
            )
            if guard.risk_level not in {"low", "medium"}:
                self._replace_with_guard_failure(session, guard)
                self._commit(session)
                raise DispenseError("安全状态已经变化，本次不再执行开柜。", status_code=409)

            if not self._medicine_information_confirmed(session.extracted_information):
                raise DispenseError("用药和过敏信息尚未确认，不能执行开柜。", status_code=409)
            direction_plans = self._existing_direction_plans(session.user_id)
            completed_direction_ids = {
                str(item.get("medicine_id") or "")
                for item in session.action_items
                if isinstance(item, dict) and item.get("ok")
            }
            safe_pool = self.safety_engine.knowledge.safe_candidate_pool(
                self._candidate_context(session),
                existing_direction_ids=set(direction_plans) | completed_direction_ids,
            )
            allowed_ids = {candidate.id for candidate in safe_pool}
            fresh_option = displayed_option
            if any(medicine.id not in allowed_ids for medicine in displayed_option.medicines):
                session.treatment_options = []
                session.can_view_medicines = False
                session.action_status = "idle"
                session.next_action = "escalate"
                session.reply = "库存、有效期或安全信息已经变化，请重新开始问询。"
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
                            today_plan_id=(
                                direction_plans.get(medicine.id, "")
                                if treatment_medicine.requires_existing_direction
                                else ""
                            ),
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

    def _advance_from_interpretation(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        interpretation: SymptomInterpretation,
        *,
        current_transcript: str = "",
    ) -> InquirySessionResponse:
        guard = self.safety_engine.assess_guardrails(
            extracted,
            session.vitals,
            ai_risk_level=interpretation.ai_risk_level,
            ai_risk_reasons=interpretation.risk_signals,
        )
        if guard.risk_level in {"high", "emergency"}:
            extracted.pending_clarification = ""
            return self._finish(
                session,
                extracted,
                source="safety_rules",
                forced_guard=guard,
            )
        if interpretation.available and interpretation.action_intent == "escalate":
            return self._finish(
                session,
                extracted,
                source=interpretation.source,
                allow_candidates=False,
                empty_message=(
                    interpretation.assistant_reply
                    or "当前情况需要医生或现场人员进一步确认，本次不展示家庭药品候选。"
                ),
            )
        if interpretation.available and interpretation.action_intent == "end":
            if self._is_explicit_end_request(current_transcript):
                session.extracted_information = extracted
                session.risk_level = guard.risk_level
                session.risk_reasons = guard.risk_reasons
                session.stage = "result"
                session.next_action = "complete"
                session.reply = interpretation.assistant_reply or "本次问询已结束。"
                session.source = interpretation.source
                session.reasoning_summary = extracted.case_summary or session.reasoning_summary
                session.title = self._title(session)
                self._clear_decision(session)
                return self._commit(session)
            return self._finish(session, extracted, source=interpretation.source)

        if interpretation.material_symptom_change:
            extracted.symptom_collection_complete = False

        # A model recommendation must not skip the patient's own symptom scope.
        # Finish establishing what is uncomfortable before asking for device data.
        if self._needs_symptom_scope_confirmation(extracted):
            session.extracted_information = extracted
            session.stage = "clarification"
            session.next_action = "ask"
            if (
                extracted.pending_clarification == "additional_symptoms"
                and self._is_scope_explanation_request(current_transcript)
            ):
                session.reply = (
                    "就是除了刚才已经说到的不适，身体现在还有没有别的明显难受；"
                    "有的话直接说，没有就说没有。"
                )
            else:
                session.reply = symptom_scope_confirmation_question(extracted)
            extracted.pending_clarification = "additional_symptoms"
            session.model_action_intent = "ask"
            session.source = interpretation.source if interpretation.available else "dialogue_policy"
            self._clear_decision(session)
            return self._commit(session)

        if self._should_measure_vitals_for_case(session, extracted, interpretation):
            session.stage = "vitals"
            session.next_action = "measure_vitals"
            session.action_reason = "当前症状可能受额温、心率和血氧影响，先读取核心体征。"
            session.reply = self._vitals_guidance(
                "为了更准确判断当前不适，需要先测量额温、心率和血氧。"
            )
            extracted.pending_clarification = ""
            session.extracted_information = extracted
            self._clear_decision(session)
            return self._commit(session)
        if (
            interpretation.action_intent == "measure_vitals"
            and not self._has_complete_vitals(session)
            and self._has_meaningful_complaint(extracted)
        ):
            session.stage = "vitals"
            session.next_action = "measure_vitals"
            session.reply = self._vitals_guidance(
                interpretation.assistant_reply
                or "这项信息会影响本次判断，需要测量额温、心率和血氧。"
            )
            extracted.pending_clarification = ""
            session.extracted_information = extracted
            self._clear_decision(session)
            return self._commit(session)

        if extracted.symptom_collection_complete:
            return self._advance_after_symptom_collection(
                session,
                extracted,
                source=interpretation.source,
            )

        locally_ready = minimum_clinical_information_ready(extracted)
        model_ready = interpretation.clinical_ready or interpretation.action_intent in {
            "analyze",
            "measure_vitals",
        }
        minimum_followups_met = (
            len(extracted.asked_clarifications)
            >= self._minimum_focused_followups(extracted)
        )
        if (
            locally_ready
            and model_ready
            and interpretation.action_intent == "analyze"
            and self._medicine_information_confirmed(extracted)
            and minimum_followups_met
        ):
            extracted.symptom_collection_complete = True
            extracted.pending_clarification = ""
            return self._finish(session, extracted, source=interpretation.source)
        if locally_ready and model_ready and minimum_followups_met:
            extracted.symptom_collection_complete = True
            extracted.pending_clarification = ""
            return self._advance_after_symptom_collection(
                session,
                extracted,
                source=interpretation.source,
            )

        if self._symptom_followup_limit_reached(session, extracted):
            # Four precise clinical questions are a hard user-experience cap.
            # Remaining uncertainty is carried into the final assessment; the
            # medicine/allergy/vitals safety chain still runs before any option.
            extracted.symptom_collection_complete = True
            extracted.pending_clarification = ""
            return self._advance_after_symptom_collection(
                session,
                extracted,
                source=interpretation.source,
            )

        proposed_question = (
            interpretation.assistant_reply
            or interpretation.follow_up_question
            if interpretation.available
            else ""
        )
        question, topic = focused_followup_question(
            extracted,
            proposed_question,
            interpretation.question_topic,
        )
        if not question or not topic:
            if locally_ready:
                extracted.symptom_collection_complete = True
                extracted.pending_clarification = ""
                return self._advance_after_symptom_collection(
                    session,
                    extracted,
                    source=interpretation.source,
                )
            return self._finish_insufficient(
                session,
                extracted,
                source=interpretation.source,
            )

        self._register_symptom_question(extracted, topic)
        session.extracted_information = extracted
        session.stage = "clarification"
        session.next_action = "ask"
        session.reply = question
        session.model_action_intent = "ask"
        session.source = interpretation.source if interpretation.available else "dialogue_policy"
        self._clear_decision(session)
        return self._commit(session)

    def _finish_insufficient(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        *,
        source: str,
        message: str = "",
    ) -> InquirySessionResponse:
        extracted.pending_clarification = ""
        session.extracted_information = extracted
        session.stage = "result"
        session.next_action = "complete"
        session.reply = message or (
            "四次关键症状核验后，仍缺少足以安全匹配药品的信息。"
            "本次先不自动给出用药方案，请补充测量后重新问询，或联系医生、药师确认。"
        )
        session.source = source or "dialogue_policy"
        session.model_action_intent = "end"
        session.action_reason = "症状追问已达上限，但关键证据仍不足。"
        self._clear_decision(session)
        session.risk_level = "medium"
        session.risk_reasons = ["关键症状信息不足"]
        session.reasoning_summary = extracted.case_summary or session.reasoning_summary
        session.title = self._title(session)
        return self._commit(session)

    def _finish(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        *,
        source: str,
        forced_guard=None,
        allow_candidates: bool = True,
        empty_message: str = "",
    ) -> InquirySessionResponse:
        guard = forced_guard or self.safety_engine.assess_guardrails(
            extracted,
            session.vitals,
            ai_risk_level=extracted.ai_risk_level,
            ai_risk_reasons=extracted.ai_risk_reasons,
        )
        options = []
        rank_source = source
        rank_message = ""
        rank_summary = ""
        rank_assessment = InquiryClinicalAssessment()
        rank_failed = False
        if (
            allow_candidates
            and guard.risk_level in {"low", "medium"}
            and self._medicine_information_confirmed(extracted)
        ):
            existing_direction_ids = set(self._existing_direction_plans(session.user_id))
            candidate_context = self._candidate_context(session)
            safe_pool = self.safety_engine.knowledge.safe_candidate_pool(
                candidate_context,
                existing_direction_ids=existing_direction_ids,
            )
            ranking_context = self._ranking_context(session, extracted, guard)
            focused_pool = self.safety_engine.knowledge.focus_candidate_pool(
                self._candidate_retrieval_text(extracted),
                safe_pool,
            )
            ranker = getattr(self.interpreter, "rank_candidates", None)
            if callable(ranker):
                ranking = ranker(
                    ranking_context,
                    [candidate.model_dump() for candidate in focused_pool],
                )
                rank_source = str(ranking.get("source") or source)
                rank_message = str(ranking.get("message") or "")
                if ranking.get("ok"):
                    rank_assessment = self._assessment_from_ranking(
                        ranking,
                        ranking_context.get("evidence_catalog") or {},
                    )
                    rank_summary = (
                        rank_assessment.summary
                        or str(ranking.get("summary") or "").strip()[:180]
                    )
                    # Ranking may involve a network round trip. Re-read the live
                    # cabinet before display and keep only candidates the model
                    # actually saw that are still eligible now.
                    fresh_pool = self.safety_engine.knowledge.safe_candidate_pool(
                        candidate_context,
                        existing_direction_ids=existing_direction_ids,
                    )
                    fresh_by_id = {candidate.id: candidate for candidate in fresh_pool}
                    fresh_focused_pool = [
                        fresh_by_id[candidate.id]
                        for candidate in focused_pool
                        if candidate.id in fresh_by_id
                    ]
                    options = self.safety_engine.knowledge.options_from_ai_selection(
                        ranking,
                        fresh_focused_pool,
                    )
                else:
                    rank_failed = True
            else:
                rank_failed = True
        if rank_assessment.summary or rank_assessment.possible_conditions:
            extracted.final_assessment = rank_assessment
        elif not extracted.final_assessment.summary:
            extracted.final_assessment = InquiryClinicalAssessment(
                summary=(extracted.case_summary or session.reasoning_summary)[:180]
            )
        session.extracted_information = extracted
        session.risk_level = guard.risk_level
        session.risk_reasons = guard.risk_reasons
        session.treatment_options = options
        session.primary_candidate = (
            self._candidate_from_treatment(options[0].medicines[0])
            if options and options[0].medicines
            else None
        )
        session.alternative_candidate = (
            self._candidate_from_treatment(options[1].medicines[0])
            if len(options) > 1 and options[1].medicines
            else None
        )
        session.source = rank_source
        session.can_view_medicines = bool(
            guard.risk_level in {"low", "medium"} and bool(options)
        )
        session.selected_option_id = ""
        session.action_status = "ready" if session.can_view_medicines else "idle"
        session.action_message = ""
        session.action_progress_index = 0
        session.action_total_items = 0
        session.action_items = []
        session.reasoning_summary = rank_summary or extracted.case_summary or session.reasoning_summary
        session.title = self._title(session)
        if guard.risk_level in {"high", "emergency"}:
            session.stage = "escalated"
            session.next_action = "escalate"
            session.reply = (
                "检测到需要立即处理的危险信号，请停止自行取药并立即联系医生或救援人员。"
                if guard.risk_level == "emergency"
                else "当前存在高风险信号，本次不展示候选药品，请尽快联系医生或现场协助人员。"
            )
        elif not self._medicine_information_confirmed(extracted):
            session.stage = "clarification"
            session.next_action = "ask"
            missing = self._missing_medicine_information(extracted)
            if missing == "used_medicines":
                window = medication_question_window(extracted.duration)
                session.reply = (
                    f"{window}，你有没有吃过、含服或外用过药？"
                    "如果用过请说药名；没有用过直接说“还没有”就可以。"
                )
                extracted.pending_clarification = "used_medicines"
            else:
                session.reply = "还需要确认一项：你有没有药物过敏，或明确不能使用的药物？"
                extracted.pending_clarification = "allergy_or_contraindication"
            session.extracted_information = extracted
            self._clear_decision(session)
        elif not options:
            if rank_failed or rank_message or not extracted.ai_available:
                extracted.pending_clarification = ""
                session.stage = "clarification"
                session.next_action = "ask"
                session.reply = (
                    "药品匹配服务这次没有稳定返回结果，已保留本次问询信息。"
                    "请稍后重新匹配，症状明显加重时请及时联系医生或药师。"
                )
                session.model_action_intent = "ask"
                session.action_reason = "药品匹配暂未完成，可在同一会话中重试。"
            elif empty_message:
                extracted.pending_clarification = ""
                session.stage = "result"
                session.next_action = "escalate"
                session.reply = empty_message
            else:
                extracted.pending_clarification = ""
                session.stage = "result"
                session.next_action = "complete"
                session.reply = (
                    "目前更适合先做基础护理和观察，暂时没有需要打开的家庭药柜。"
                    "如果出现红肿、持续疼痛、发热或症状明显加重，请及时联系医生或家人。"
                )
        else:
            extracted.pending_clarification = ""
            session.stage = "result"
            session.next_action = "show_recommendation"
            option_count = len(options)
            option_text = (
                "我整理了一个主方案和一个备选，你只需要选择其中一项。"
                if option_count > 1
                else "结合这些信息，我整理了一个更贴近当前情况的选择。"
            )
            natural_summary = self._natural_summary(session.reasoning_summary)
            session.reply = f"{natural_summary}{option_text}"
        return self._commit(session)

    @staticmethod
    def _assessment_from_ranking(
        ranking: dict,
        evidence_catalog: dict[str, str],
    ) -> InquiryClinicalAssessment:
        raw = ranking.get("assessment") if isinstance(ranking, dict) else None
        raw = raw if isinstance(raw, dict) else {}

        def text(value: object, limit: int) -> str:
            return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

        def text_list(value: object, limit: int, item_limit: int) -> list[str]:
            if not isinstance(value, list):
                return []
            return [
                item_text
                for item in value[:limit]
                if (item_text := text(item, item_limit))
            ]

        def safe_action_list(
            value: object,
            *,
            block_medication_directions: bool = False,
        ) -> list[str]:
            blocked_phrases = (
                "确诊",
                "肯定是",
                "已经诊断",
                "开柜",
                "药柜",
                "柜门",
                "直接取药",
                "加倍",
                "增加剂量",
                "替代医嘱",
                "停用慢病药",
            )
            safe: list[str] = []
            for item in text_list(value, 3, 90):
                if any(phrase in item for phrase in blocked_phrases):
                    continue
                if block_medication_directions and re.search(
                    r"服用|口服|含服|再服|加服|外用|涂抹|滴入|喷用|"
                    r"吃(?!不下|不进|不了)",
                    item,
                ):
                    # The model may suggest observation or basic care, but all
                    # medicine names and directions must come from the
                    # deterministic, inventory-backed treatment options.
                    continue
                if block_medication_directions and re.search(
                    r"(?:建议|可以|可|考虑|继续|改用|使用).{0,18}"
                    r"(?:药|片|胶囊|颗粒|口服液|丸|散|膏|凝胶|喷雾|滴剂|"
                    r"布洛芬|芬必得|阿莫西林|头孢|奥司他韦|蒙脱石|碘伏)",
                    item,
                ):
                    continue
                if re.search(
                    r"(?:自行|直接).{0,8}(?:服用|口服|吃|使用).{0,16}"
                    r"(?:\d|[一二两三四五六七八九十半]+)(?:片|粒|袋|毫克|克|次)",
                    item,
                ):
                    continue
                safe.append(item)
            return safe

        def safe_condition_name(value: object) -> str:
            name = text(value, 36)
            name = re.sub(
                r"^(?:(?:已经|已|可以|可)?(?:确诊(?:为)?|诊断(?:为)?|判定(?:为)?)|"
                r"(?:肯定|一定)是)\s*",
                "",
                name,
            ).strip()
            if any(
                phrase in name
                for phrase in ("开柜", "药柜", "柜门", "取药", "服药", "增加剂量", "处方")
            ):
                return ""
            return name

        conditions = []
        for item in raw.get("possible_conditions") or []:
            if not isinstance(item, dict):
                continue
            name = safe_condition_name(item.get("name"))
            if not name:
                continue
            likelihood = str(item.get("likelihood") or "possible").strip()
            if likelihood not in {"more_likely", "possible", "needs_exclusion"}:
                likelihood = "possible"

            def mapped_evidence(field: str) -> list[str]:
                ids = item.get(field)
                if not isinstance(ids, list):
                    return []
                return [
                    evidence_catalog[evidence_id]
                    for raw_id in ids[:2]
                    if (evidence_id := str(raw_id or "").strip()) in evidence_catalog
                ]

            conditions.append(
                {
                    "name": name,
                    "likelihood": likelihood,
                    "supporting_evidence": mapped_evidence("supporting_evidence_ids"),
                    "non_supporting_evidence": mapped_evidence("non_supporting_evidence_ids"),
                }
            )
            if len(conditions) >= 3:
                break
        # Do not display free-form model prose as the clinical summary.  Even
        # when condition evidence IDs are valid, prose can still turn an
        # unknown fact (for example "体温未测") into a false negative claim
        # ("无发热").  Build the summary from the already grounded condition
        # names and mapped evidence instead.
        summary = InquiryOrchestrator._grounded_assessment_summary(
            conditions,
            evidence_catalog,
        )
        return InquiryClinicalAssessment(
            summary=summary,
            possible_conditions=conditions,
            next_steps=safe_action_list(
                raw.get("next_steps"),
                block_medication_directions=True,
            ),
            seek_care_if=safe_action_list(
                raw.get("seek_care_if"),
                block_medication_directions=True,
            ),
        )

    @staticmethod
    def _grounded_assessment_summary(
        conditions: list[dict[str, object]],
        evidence_catalog: dict[str, str],
    ) -> str:
        if not conditions:
            return "现有信息不足以形成明确的可能性排序，需结合体征和症状变化继续判断。"

        names_by_level: dict[str, list[str]] = {
            "more_likely": [],
            "possible": [],
            "needs_exclusion": [],
        }
        supporting_labels: list[str] = []
        for condition in conditions:
            likelihood = str(condition.get("likelihood") or "possible")
            name = str(condition.get("name") or "").strip()
            if name and name not in names_by_level.get(likelihood, []):
                names_by_level.setdefault(likelihood, []).append(name)
            for evidence in condition.get("supporting_evidence") or []:
                label = str(evidence or "").split("：", 1)[0].strip()
                if label and label not in supporting_labels:
                    supporting_labels.append(label)

        lead = f"结合{'、'.join(supporting_labels[:4])}，" if supporting_labels else ""
        clauses: list[str] = []
        if names_by_level["more_likely"]:
            clauses.append(f"目前更需要考虑{'、'.join(names_by_level['more_likely'])}")
        if names_by_level["possible"]:
            prefix = "也可能与" if clauses else "目前可能与"
            clauses.append(f"{prefix}{'、'.join(names_by_level['possible'])}有关")
        if names_by_level["needs_exclusion"]:
            clauses.append(f"{'、'.join(names_by_level['needs_exclusion'])}仍需观察或排除")

        first_sentence = lead + "；".join(clauses) + "。"
        uncertain_labels: list[str] = []
        for evidence in evidence_catalog.values():
            if not any(marker in evidence for marker in ("尚不确定", "未测", "测量未完成")):
                continue
            label = str(evidence).split("：", 1)[0].strip()
            if label and label not in uncertain_labels:
                uncertain_labels.append(label)
        second_sentence = (
            f"{'、'.join(uncertain_labels[:3])}仍未确认，需结合后续测量和症状变化继续判断。"
            if uncertain_labels
            else "仍需结合后续体征和症状变化继续判断。"
        )
        return (first_sentence + second_sentence)[:180]

    def _model_context(
        self,
        session: InquirySessionResponse,
        *,
        include_current_transcript: str = "",
    ) -> dict:
        messages = [
            {"role": message.role, "content": message.content}
            for message in session.messages
        ]
        if include_current_transcript:
            messages.append({"role": "user", "content": include_current_transcript})
        messages = messages[-12:]
        context = session.extracted_information.model_dump()
        context["symptoms_text"] = self._chief_complaint(
            session.extracted_information.observations,
            session.extracted_information.symptoms_text,
            include_current_transcript,
        )
        context.update(
            {
                "current_stage": session.stage,
                "conversation_turns": self._current_user_turn_count(session),
                "symptom_followups_remaining": max(
                    0,
                    self._MAX_SYMPTOM_FOLLOWUPS
                    - len(session.extracted_information.asked_clarifications),
                ),
                "maximum_symptom_followups": self._MAX_SYMPTOM_FOLLOWUPS,
                "conversation": messages,
                "vitals": session.vitals or {},
                "recent_history": self._history_context(session).model_context(),
            }
        )
        return context

    def _advance_after_symptom_collection(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        *,
        source: str,
    ) -> InquirySessionResponse:
        extracted.symptom_collection_complete = True
        used = extracted.used_medicines.strip()
        if not self._safety_answer_confirmed(used):
            session.stage = "clarification"
            session.next_action = "ask"
            window = medication_question_window(extracted.duration)
            session.reply = (
                f"{window}，请确认具体用过药的药名；如果确实没有用过，直接说“还没有”。"
                if used
                else (
                    f"{window}，你有没有吃过、含服或外用过药？"
                    "如果用过请说药名；没有用过直接说“还没有”就可以。"
                )
            )
            extracted.pending_clarification = "used_medicines"
            session.extracted_information = extracted
            session.source = source
            self._clear_decision(session)
            return self._commit(session)

        allergy = extracted.allergy_or_contraindication.strip()
        if not self._safety_answer_confirmed(allergy):
            session.stage = "clarification"
            session.next_action = "ask"
            session.reply = "接下来确认用药安全：你有没有药物过敏，或明确不能使用的药物？"
            extracted.pending_clarification = "allergy_or_contraindication"
            session.extracted_information = extracted
            session.source = source
            self._clear_decision(session)
            return self._commit(session)

        vitals_status = str((session.vitals or {}).get("status") or "")
        if not self._has_complete_vitals(session) and vitals_status not in {
            "failed",
            "cancelled",
            "unavailable",
        }:
            extracted.pending_clarification = ""
            session.extracted_information = extracted
            session.stage = "vitals"
            session.next_action = "measure_vitals"
            session.reply = self._vitals_guidance(
                "症状和用药安全信息已经确认，接下来读取额温、心率和血氧。"
            )
            session.source = source
            session.action_reason = "症状追问已完成，进入核心体征核验。"
            self._clear_decision(session)
            return self._commit(session)

        extracted.pending_clarification = ""
        return self._finish(session, extracted, source=source)

    @staticmethod
    def _model_profile(session: InquirySessionResponse) -> dict[str, object]:
        return {
            "name": session.user_name,
            "age": session.user_age,
            "profile": session.user_profile,
            "allergies": session.user_allergies,
        }

    def _ranking_context(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        guard,
    ) -> dict:
        evidence_catalog = self._evidence_catalog(session, extracted)
        return {
            "person": self._model_profile(session),
            "case_summary": extracted.case_summary,
            "observations": [value.model_dump() for value in extracted.observations],
            "uncertainties": extracted.uncertainties,
            "duration": extracted.duration,
            "used_medicines": extracted.used_medicines,
            "allergy_or_contraindication": extracted.allergy_or_contraindication,
            "vitals": session.vitals or {},
            "risk_level": guard.risk_level,
            "risk_reasons": guard.risk_reasons,
            "history_relationship": extracted.history_relationship.model_dump(),
            "evidence_catalog": evidence_catalog,
        }

    @staticmethod
    def _evidence_catalog(
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
    ) -> dict[str, str]:
        catalog: dict[str, str] = {}
        for index, observation in enumerate(extracted.observations[:12], start=1):
            status_label = {
                "present": "存在",
                "absent": "未出现",
                "uncertain": "尚不确定",
            }.get(observation.status, observation.status)
            evidence = observation.evidence.strip() or observation.concept
            catalog[f"obs-{index}"] = f"{observation.concept}：{status_label}（{evidence}）"[:140]
        if extracted.duration.strip():
            catalog["episode-onset"] = f"本次不适起病：{extracted.duration.strip()}"[:140]
        if extracted.used_medicines.strip():
            catalog["episode-medication"] = f"本次已用药：{extracted.used_medicines.strip()}"[:140]
        if extracted.allergy_or_contraindication.strip():
            catalog["person-allergy"] = (
                f"过敏或明确禁忌：{extracted.allergy_or_contraindication.strip()}"
            )[:140]
        if session.user_profile.strip():
            catalog["person-history"] = f"既往资料：{session.user_profile.strip()}"[:140]
        vitals = session.vitals or {}
        if vitals.get("temperature") is not None:
            catalog["vital-temperature"] = f"本次额温：{vitals.get('temperature')}℃"
        if vitals.get("heart_rate") is not None:
            catalog["vital-heart-rate"] = f"本次心率：{vitals.get('heart_rate')}次/分"
        if vitals.get("spo2") is not None:
            catalog["vital-spo2"] = f"本次血氧：{vitals.get('spo2')}%"
        if vitals.get("status") in {"cancelled", "failed"}:
            catalog["vital-status"] = "本次体征：测量未完成"
        return catalog

    def _candidate_context(self, session: InquirySessionResponse) -> str:
        return "；".join(
            value.strip()
            for value in (
                session.user_profile,
                session.user_allergies,
                session.extracted_information.allergy_or_contraindication,
                (
                    f"已用药：{session.extracted_information.used_medicines}"
                    if session.extracted_information.used_medicines
                    and session.extracted_information.used_medicines != "未使用"
                    else ""
                ),
            )
            if value and value.strip()
        )

    @staticmethod
    def _existing_direction_plans(user_id: str) -> dict[str, str]:
        if not str(user_id or "").strip():
            return {}
        from .records_service import RecordsService

        return {
            plan.medicine_id: plan.id
            for plan in RecordsService().list_today_plans(due_only=True)
            if plan.service_user_id == user_id and plan.status == "待执行"
        }

    @staticmethod
    def _medicine_information_confirmed(extracted: InquiryExtractedInformation) -> bool:
        used = extracted.used_medicines.strip()
        allergy = extracted.allergy_or_contraindication.strip()
        return bool(
            InquiryOrchestrator._safety_answer_confirmed(used)
            and InquiryOrchestrator._safety_answer_confirmed(allergy)
        )

    @staticmethod
    def _candidate_retrieval_text(extracted: InquiryExtractedInformation) -> str:
        return "；".join(
            value
            for value in (
                extracted.case_summary,
                extracted.symptoms_text,
                "；".join(
                    f"{item.concept}：{item.evidence}"
                    for item in extracted.observations
                    if item.status == "present"
                ),
            )
            if value
        )

    @staticmethod
    def _safety_answer_confirmed(value: str) -> bool:
        text = str(value or "").strip()
        return bool(
            text
            and not any(
                term in text
                for term in (
                    "不确定", "不知道", "不清楚", "不详", "记不清", "无法确认",
                    "不能明确", "说不出药名", "不知道药名", "药名不详",
                )
            )
        )

    @staticmethod
    def _missing_medicine_information(extracted: InquiryExtractedInformation) -> str:
        used = extracted.used_medicines.strip()
        if not used or used == "不确定":
            return "used_medicines"
        return "allergy_or_contraindication"

    @staticmethod
    def _is_explicit_end_request(transcript: str) -> bool:
        text = transcript.strip()
        return any(
            phrase in text
            for phrase in (
                "不继续了",
                "先不继续",
                "结束问询",
                "结束对话",
                "不问了",
                "先这样",
                "到这里",
                "退出问询",
            )
        )

    @staticmethod
    def _is_ranking_retry_request(transcript: str) -> bool:
        text = transcript.strip()
        return any(
            phrase in text
            for phrase in ("重新匹配", "再匹配一次", "重试匹配", "再试一次", "再试试")
        )

    @staticmethod
    def _ranking_retry_pending(session: InquirySessionResponse) -> bool:
        extracted = session.extracted_information
        return bool(
            session.stage == "clarification"
            and session.next_action == "ask"
            and extracted.symptom_collection_complete
            and not extracted.pending_clarification
            and not session.treatment_options
            and "重新匹配" in session.reply
        )

    @staticmethod
    def _has_meaningful_complaint(extracted: InquiryExtractedInformation) -> bool:
        if extracted.case_summary.strip():
            return True
        return any(
            item.status == "present" and bool(item.evidence.strip())
            for item in extracted.observations
        )

    @classmethod
    def _needs_symptom_scope_confirmation(
        cls,
        extracted: InquiryExtractedInformation,
    ) -> bool:
        return bool(
            cls._has_meaningful_complaint(extracted)
            and not extracted.symptom_scope_confirmed
        )

    @staticmethod
    def _is_scope_explanation_request(transcript: str) -> bool:
        text = str(transcript or "").strip()
        return any(
            phrase in text
            for phrase in ("什么意思", "什么算", "有哪些", "怎么回答", "没听懂", "为什么要问")
        )

    @staticmethod
    def _minimum_focused_followups(extracted: InquiryExtractedInformation) -> int:
        """Avoid a premature recommendation while respecting rich first turns."""
        resolved_detail_topics = {
            topic
            for topic, evidence in extracted.clarification_answers.items()
            if topic not in {"main_symptom", "additional_symptoms"}
            and str(evidence or "").strip()
        }
        if len(resolved_detail_topics) >= 3:
            return 0
        present_count = sum(
            1 for item in extracted.observations if item.status == "present"
        )
        return 3 if present_count >= 2 else 2

    @staticmethod
    def _require_current_real_vitals(request: InquiryVitalsRequest) -> None:
        sources = {
            request.temperature_source,
            request.heart_rate_source,
            request.spo2_source,
        }
        readings = (
            request.temperature,
            request.heart_rate,
            request.spo2,
            request.systolic_pressure,
            request.diastolic_pressure,
            request.respiratory_rate,
            request.hrv_sdnn,
            request.hrv_rmssd,
        )
        forbidden_sources = {"demo_fallback", "history_fallback", "historical_fallback"}
        if (
            request.spo2_demo_fallback
            or request.historical_fallback
            or bool(sources & forbidden_sources)
            or (request.status != "complete" and any(value is not None for value in readings))
            or (
                request.status == "complete"
                and (
                    request.temperature is None
                    or request.heart_rate is None
                    or request.spo2 is None
                    or request.temperature_source != "gy614_sensor"
                    or request.heart_rate_source != "uart8_sensor"
                    or request.spo2_source != "uart8_sensor"
                )
            )
        ):
            raise ValueError("只有本次真实测量可以进入问询体征。")

    @staticmethod
    def _has_complete_vitals(session: InquirySessionResponse) -> bool:
        vitals = session.vitals or {}
        status = str(vitals.get("status") or "complete")
        return bool(
            status == "complete"
            and vitals.get("temperature")
            and vitals.get("heart_rate")
            and vitals.get("spo2")
        )

    @classmethod
    def _should_measure_vitals_for_case(
        cls,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        interpretation: SymptomInterpretation,
    ) -> bool:
        if interpretation.source != "local_llm":
            return False
        if interpretation.action_intent == "measure_vitals":
            return False
        if cls._has_complete_vitals(session):
            return False
        if str((session.vitals or {}).get("status") or "") in {"failed", "cancelled"}:
            return False
        if not cls._has_meaningful_complaint(extracted):
            return False
        text = "；".join(
            value
            for value in (
                extracted.case_summary,
                extracted.symptoms_text,
                "；".join(item.evidence for item in extracted.observations if item.status == "present"),
            )
            if value
        )
        needs_core_vitals = (
            "中暑", "暑湿", "暴晒", "头晕", "发热", "高热", "乏力", "恶心", "呕吐",
            "腹泻", "头痛", "胸闷", "心慌", "气短", "呼吸", "发冷", "出汗",
        )
        if not any(term in text for term in needs_core_vitals):
            return False
        # Let the model ask for the first missing context item once. After the
        # complaint has a duration, a missed model action cannot skip vitals.
        return bool(extracted.duration.strip() or cls._current_user_turn_count(session) >= 2)

    @staticmethod
    def _vitals_guidance(reply: str) -> str:
        base = reply.strip().rstrip("。！？!?")
        operation = "请将额头对准屏幕上方，并把手指平稳放在感应区。准备好后点击开始测量。"
        if "额头" in base and "手指" in base and "开始测量" in base:
            return f"{base}。"
        return f"{base}。{operation}" if base else operation

    @staticmethod
    def _vitals_event_message(vitals: dict[str, object]) -> str:
        status = str(vitals.get("status") or "complete")
        if status == "cancelled":
            return "用户取消了本次体征测量，请结合已有信息自然继续问询。"
        if status == "failed":
            detail = str(vitals.get("error_message") or "设备未获得完整读数")
            return f"本次体征测量未完成：{detail}。请结合已有信息自然继续问询。"
        return (
            f"体征测量完成：额温 {vitals.get('temperature')}℃，"
            f"心率 {vitals.get('heart_rate')}次/分，血氧 {vitals.get('spo2')}%。"
        )

    @staticmethod
    def _candidate_from_treatment(value):
        from ..schemas.inquiry import CandidateMedicine

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
            tags=value.tags,
            contraindications=value.contraindications,
            aliases=value.aliases,
            active_ingredients=value.active_ingredients,
            match_reason=value.match_reason,
            requires_existing_direction=value.requires_existing_direction,
        )

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
                "SELECT id, name, age, profile, allergies, note FROM service_users WHERE id=?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def _profile_with_note(user: dict[str, object]) -> str:
        values = [
            " ".join(str(user.get(field) or "").split()).strip()
            for field in ("profile", "note")
        ]
        return "；".join(dict.fromkeys(value for value in values if value))[:360]

    @staticmethod
    def _merge_interpretation(
        session: InquirySessionResponse,
        transcript: str,
        interpretation: SymptomInterpretation,
    ) -> InquiryExtractedInformation:
        current = session.extracted_information
        observation_map = {item.concept: item for item in current.observations}
        if (
            interpretation.material_symptom_change
            and interpretation.symptom_change_type == "replace"
        ):
            replaced = {
                re.sub(r"\s+", "", concept)
                for concept in interpretation.replaced_concepts
                if str(concept or "").strip()
            }
            if not replaced:
                prior_present = [
                    item.concept for item in current.observations if item.status == "present"
                ]
                new_present = {
                    item.concept for item in interpretation.observations if item.status == "present"
                }
                if len(prior_present) == 1 and new_present and prior_present[0] not in new_present:
                    replaced.add(re.sub(r"\s+", "", prior_present[0]))
            observation_map = {
                concept: item
                for concept, item in observation_map.items()
                if re.sub(r"\s+", "", concept) not in replaced
            }
        for item in interpretation.observations:
            observation_map[item.concept] = item
        observations = list(observation_map.values())
        dimensions = list(
            dict.fromkeys(
                item.concept
                for item in observations
                if item.status == "present"
            )
        )
        evidence = {
            item.concept: item.evidence
            for item in observations
            if item.status == "present" and item.evidence
        }
        used_medicines = interpretation.used_medicines or current.used_medicines
        allergy_or_contraindication = (
            interpretation.allergy_or_contraindication
            or current.allergy_or_contraindication
            or session.user_allergies
        )
        pending_before = current.pending_clarification.strip()
        if pending_before == "allergy_or_contraindication":
            contextual_allergy = SymptomInterpreter.allergy_answer(
                transcript,
                allow_short_answer=True,
            )
            if contextual_allergy:
                allergy_or_contraindication = contextual_allergy
        elif pending_before == "used_medicines":
            contextual_medicine_use = SymptomInterpreter.used_medicine_answer(
                transcript,
                allow_short_answer=True,
            )
            if contextual_medicine_use:
                used_medicines = contextual_medicine_use
        if is_contextual_negative_answer(transcript):
            previous_question = next(
                (
                    message.content
                    for message in reversed(session.messages)
                    if message.role == "assistant"
                ),
                "",
            )
            asks_allergy = any(
                term in previous_question
                for term in ("过敏", "禁忌", "不能使用", "不能用")
            )
            asks_used_medicines = any(
                term in previous_question
                for term in ("用过药", "用药", "吃过药", "吃药", "服药")
            )
            if pending_before == "allergy_or_contraindication":
                allergy_or_contraindication = "无"
            elif pending_before == "used_medicines":
                used_medicines = "未使用"
            elif asks_allergy:
                if not allergy_or_contraindication:
                    allergy_or_contraindication = "无"
            elif asks_used_medicines and not used_medicines:
                used_medicines = "未使用"
        clarification_answers = dict(current.clarification_answers)
        if interpretation.material_symptom_change:
            # Keep episode-wide facts that remain useful, but invalidate every
            # symptom-specific slot and restart the four-question budget.
            clarification_answers = {
                topic: evidence_text
                for topic, evidence_text in clarification_answers.items()
                if topic in {"onset", "fever"}
            }
        semantic_evidence = normalize_topic_evidence(interpretation.topic_evidence)
        for topic, evidence_text in explicit_topic_evidence(transcript).items():
            semantic_evidence.setdefault(topic, evidence_text)
        for topic in normalize_answered_topics(interpretation.answered_topics_this_turn):
            if topic not in SYMPTOM_QUESTION_TOPICS:
                continue
            evidence_text = semantic_evidence.get(topic)
            if evidence_text:
                clarification_answers[topic] = evidence_text
        for topic, evidence_text in semantic_evidence.items():
            if topic in SYMPTOM_QUESTION_TOPICS:
                clarification_answers[topic] = evidence_text

        compact_transcript = transcript.strip()
        asks_for_explanation = any(
            phrase in compact_transcript
            for phrase in ("什么意思", "有什么区别", "为什么", "没听懂", "怎么回答")
        )
        if (
            pending_before in SYMPTOM_QUESTION_TOPICS
            and pending_before not in clarification_answers
            and compact_transcript
            and not asks_for_explanation
            and not interpretation.material_symptom_change
        ):
            clarification_answers[pending_before] = compact_transcript[:180]

        duration = (
            interpretation.duration
            or SymptomInterpreter.duration_answer(transcript)
            or current.duration
        )
        if duration:
            clarification_answers.setdefault("onset", duration)

        symptoms_text = InquiryOrchestrator._chief_complaint(
            observations,
            "" if interpretation.material_symptom_change else current.symptoms_text,
            transcript,
        )
        if symptoms_text:
            clarification_answers.setdefault("main_symptom", symptoms_text)

        return InquiryExtractedInformation(
            case_summary=interpretation.case_summary or (
                "" if interpretation.material_symptom_change else current.case_summary
            ),
            observations=observations,
            uncertainties=interpretation.uncertainties,
            history_relationship=interpretation.history_relationship,
            ai_risk_level=interpretation.ai_risk_level or current.ai_risk_level,
            ai_risk_reasons=list(dict.fromkeys(interpretation.risk_signals)),
            ai_available=interpretation.available,
            symptom_dimensions=dimensions,
            dimension_evidence=evidence,
            symptom_features=[],
            feature_evidence={},
            clarification_answers=clarification_answers,
            asked_clarifications=(
                []
                if interpretation.material_symptom_change
                else list(current.asked_clarifications)
            ),
            pending_clarification=(
                "" if interpretation.material_symptom_change else current.pending_clarification
            ),
            symptom_scope_confirmed=(
                False
                if interpretation.material_symptom_change
                else bool(
                    current.symptom_scope_confirmed
                    or interpretation.symptom_scope_complete
                )
            ),
            symptom_revision=(
                current.symptom_revision + 1
                if interpretation.material_symptom_change
                else current.symptom_revision
            ),
            symptom_collection_complete=(
                False
                if interpretation.material_symptom_change
                else current.symptom_collection_complete
            ),
            symptoms_text=symptoms_text,
            duration=duration,
            used_medicines=used_medicines,
            allergy_or_contraindication=allergy_or_contraindication,
            confidence=max(current.confidence, interpretation.confidence),
            final_assessment=InquiryClinicalAssessment(),
        )

    @staticmethod
    def _promote_material_symptom_addition(
        current: InquiryExtractedInformation,
        interpretation: SymptomInterpretation,
    ) -> None:
        """Start a new question cycle only when ``add`` introduces a real symptom.

        A refinement of an existing complaint must keep the current four-question
        budget.  Conversely, a newly present concept can change risk and the next
        useful question even when the model omitted its material-change flag.
        """
        if (
            current.pending_clarification == "additional_symptoms"
            and interpretation.symptom_scope_complete
            and interpretation.symptom_change_type == "add"
        ):
            # This is the expected positive answer to the one scope question,
            # not a later change to an already established complaint. Merge it
            # into the initial scope and begin focused clarification once.
            interpretation.material_symptom_change = False
            return
        if (
            interpretation.material_symptom_change
            or interpretation.symptom_change_type != "add"
        ):
            return
        existing_concepts = {
            re.sub(r"\s+", "", item.concept)
            for item in current.observations
            if item.status == "present" and item.concept.strip()
        }
        existing_concepts.update(
            re.sub(r"\s+", "", part)
            for part in current.symptoms_text.split("、")
            if part.strip()
        )
        if not existing_concepts:
            return
        added_concepts = {
            re.sub(r"\s+", "", item.concept)
            for item in interpretation.observations
            if item.status == "present" and item.concept.strip()
        } - existing_concepts
        if added_concepts:
            interpretation.material_symptom_change = True

    @staticmethod
    def _chief_complaint(observations, current: str, transcript: str) -> str:
        concepts: list[str] = []
        for value in str(current or "").split("、"):
            normalized = " ".join(value.split()).strip()
            if normalized and normalized not in concepts:
                concepts.append(normalized)
        for observation in observations:
            if observation.status != "present":
                continue
            concept = " ".join(str(observation.concept or "").split()).strip()
            if concept:
                for separator in ("、", "；", "，", ","):
                    concept = concept.split(separator, 1)[0]
                if concept and concept not in concepts:
                    concepts.append(concept)

        for concept in InquiryOrchestrator._explicit_symptom_labels(transcript):
            if concept not in concepts:
                concepts.append(concept)
        if concepts:
            return "、".join(concepts[:4])[:80]

        fallback = str(current or transcript or "").strip()
        if any(
            phrase in fallback
            for phrase in ("不知道怎么说", "说不清楚", "没法描述", "不知道如何描述")
        ):
            return ""
        for separator in ("、", "；", "，", "。", ",", ".", "！", "？"):
            fallback = fallback.split(separator, 1)[0]
        for prefix in ("我感觉", "我觉得", "我有一点", "我有点", "有一点", "有点"):
            if fallback.startswith(prefix):
                fallback = fallback[len(prefix) :].strip()
                break
        return fallback[:24]

    @staticmethod
    def _explicit_symptom_labels(transcript: str) -> list[str]:
        """Preserve symptoms literally stated by the user; never infer a diagnosis."""
        text = str(transcript or "").strip()
        patterns = (
            (r"嗓子(?:疼|痛)|喉咙(?:疼|痛)|咽(?:喉)?(?:疼|痛)", "咽喉疼痛"),
            (r"头(?:有点|有一点|很|特别|剧烈)?(?:疼|痛)|头疼|头痛", "头痛"),
            (r"头晕|眩晕", "头晕"),
            (r"中暑|暑热不适", "暑热不适"),
            (r"咳嗽|咳痰", "咳嗽"),
            (r"流(?:清|黄)?鼻涕", "流鼻涕"),
            (r"鼻塞", "鼻塞"),
            (r"发热|发烧", "发热"),
            (r"发冷|怕冷", "发冷"),
            (r"腹泻|拉肚子|稀便", "腹泻"),
            (r"便秘|排不出", "便秘"),
            (r"恶心", "恶心"),
            (r"呕吐|想吐", "呕吐"),
            (r"胃痛|腹痛|肚子痛", "腹痛"),
            (r"反酸|烧心", "反酸烧心"),
            (r"尿痛|排尿痛", "尿痛"),
            (r"尿频", "尿频"),
            (r"皮疹|红疹", "皮疹"),
            (r"瘙痒|发痒", "瘙痒"),
            (r"割伤|擦伤|伤口|出血", "外伤"),
        )
        labels: list[str] = []
        for pattern, label in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            prefix = text[max(0, match.start() - 6):match.start()]
            if re.search(r"(?:没有|并没有|没|不是|不|无|否认).{0,3}$", prefix):
                continue
            labels.append(label)
        return list(dict.fromkeys(labels))

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
    def _current_user_turn_count(session: InquirySessionResponse) -> int:
        # The current transcript is persisted before this in-memory session is refreshed.
        return sum(1 for message in session.messages if message.role == "user") + 1

    @classmethod
    def _register_symptom_question(
        cls,
        extracted: InquiryExtractedInformation,
        topic: str,
    ) -> None:
        if topic not in SYMPTOM_QUESTION_TOPICS:
            return
        if topic == extracted.pending_clarification or topic in extracted.asked_clarifications:
            extracted.pending_clarification = topic
            extracted.symptom_collection_complete = False
            return
        if len(extracted.asked_clarifications) >= cls._MAX_SYMPTOM_FOLLOWUPS:
            return
        extracted.asked_clarifications.append(topic)
        extracted.pending_clarification = topic
        extracted.symptom_collection_complete = False

    @classmethod
    def _symptom_followup_limit_reached(
        cls,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation | None = None,
    ) -> bool:
        # Count only symptom questions actually shown by the assistant. The
        # opening complaint, medicine reconciliation, allergy check and vitals
        # do not consume this four-question budget.
        return (
            len((extracted or session.extracted_information).asked_clarifications)
            >= cls._MAX_SYMPTOM_FOLLOWUPS
        )

    def _history_context(self, session: InquirySessionResponse) -> InquiryHistoryContext:
        return self.history_service.context_for(
            session.user_id,
            session.session_id,
        )

    @staticmethod
    def _option(options, option_id: str):
        return next((option for option in options if option.option_id == option_id), None)

    @staticmethod
    def _replace_with_guard_failure(session: InquirySessionResponse, guard) -> None:
        session.risk_level = guard.risk_level
        session.risk_reasons = guard.risk_reasons
        session.primary_candidate = None
        session.alternative_candidate = None
        session.treatment_options = []
        session.can_view_medicines = False
        session.selected_option_id = ""
        session.action_status = "idle"
        session.action_progress_index = 0
        session.action_total_items = 0
        session.action_items = []
        session.stage = "escalated"
        session.next_action = "escalate"
        session.action_message = "安全状态已经变化，本次不再执行开柜。"
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
