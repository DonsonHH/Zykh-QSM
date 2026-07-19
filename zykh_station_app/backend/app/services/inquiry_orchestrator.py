from __future__ import annotations

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

        existing_context = self._model_context(session, include_current_transcript=transcript)
        interpretation = self.interpreter.interpret(
            transcript,
            existing_context,
            self._model_profile(session),
        )
        extracted = self._merge_interpretation(session, transcript, interpretation)
        session.extracted_information = extracted
        session.source = interpretation.source
        session.reasoning_summary = interpretation.reasoning_summary
        session.model_action_intent = interpretation.action_intent
        session.action_reason = interpretation.action_reason
        return self._advance_from_interpretation(session, extracted, interpretation)

    def attach_vitals(self, session_id: str, request: InquiryVitalsRequest) -> InquirySessionResponse:
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
            safe_pool = self.safety_engine.knowledge.safe_candidate_pool(
                self._candidate_context(session)
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
    ) -> InquirySessionResponse:
        guard = self.safety_engine.assess_guardrails(
            extracted,
            session.vitals,
            ai_risk_level=interpretation.ai_risk_level,
            ai_risk_reasons=interpretation.risk_signals,
        )
        if guard.risk_level in {"high", "emergency"}:
            return self._finish(
                session,
                extracted,
                source="safety_rules",
                forced_guard=guard,
            )
        if not interpretation.available:
            session.stage = "clarification"
            session.next_action = "ask"
            session.reply = "连接有些不稳定，刚才的内容已经保留。请再说一次最后这句话，我会从这里继续。"
            session.model_action_intent = "ask"
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
            self._clear_decision(session)
            return self._commit(session)
        if interpretation.action_intent == "measure_vitals":
            session.stage = "clarification"
            session.next_action = "ask"
            session.reply = (
                "请先说说现在最明显的不舒服是什么。"
                if not self._has_meaningful_complaint(extracted)
                else "本次核心体征已经记录，请继续说说症状目前有什么变化。"
            )
            self._clear_decision(session)
            return self._commit(session)
        if interpretation.action_intent == "ask":
            session.stage = "clarification"
            session.next_action = "ask"
            session.reply = (
                interpretation.assistant_reply
                or interpretation.follow_up_question
                or "请再说说目前最明显的变化。"
            )
            self._clear_decision(session)
            return self._commit(session)
        if interpretation.action_intent == "escalate":
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
        if interpretation.action_intent == "end":
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
        rank_failed = False
        if (
            allow_candidates
            and guard.risk_level in {"low", "medium"}
            and self._medicine_information_confirmed(extracted)
        ):
            safe_pool = self.safety_engine.knowledge.safe_candidate_pool(
                self._candidate_context(session)
            )
            ranker = getattr(self.interpreter, "rank_candidates", None)
            if callable(ranker):
                ranking = ranker(
                    self._ranking_context(session, extracted, guard),
                    [candidate.model_dump() for candidate in safe_pool],
                )
                rank_source = str(ranking.get("source") or source)
                rank_message = str(ranking.get("message") or "")
                if ranking.get("ok"):
                    options = self.safety_engine.knowledge.options_from_ai_selection(
                        ranking,
                        safe_pool,
                    )
                else:
                    rank_failed = True
            else:
                rank_failed = True
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
        session.reasoning_summary = extracted.case_summary or session.reasoning_summary
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
            session.stage = "result"
            session.next_action = "escalate"
            session.reply = "本次用药或过敏信息尚未确认，可以继续查看健康提示，但暂不生成取药候选。"
        elif not options:
            if rank_failed or rank_message or not extracted.ai_available:
                session.stage = "clarification"
                session.next_action = "ask"
                session.reply = (
                    "分析连接有些不稳定，本次信息已经保留。"
                    "请稍后说“继续分析”，我会从这里重新尝试。"
                )
            elif empty_message:
                session.stage = "result"
                session.next_action = "escalate"
                session.reply = empty_message
            else:
                session.stage = "result"
                session.next_action = "escalate"
                session.reply = "当前没有适合这次情况的家庭药品候选，请联系医生或家人协助。"
        else:
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
                "conversation": messages,
                "vitals": session.vitals or {},
                "recent_history": self._history_context(session).model_context(),
            }
        )
        return context

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
        }

    def _candidate_context(self, session: InquirySessionResponse) -> str:
        return "；".join(
            value.strip()
            for value in (
                session.user_profile,
                session.user_allergies,
                session.extracted_information.allergy_or_contraindication,
            )
            if value and value.strip()
        )

    @staticmethod
    def _medicine_information_confirmed(extracted: InquiryExtractedInformation) -> bool:
        used = extracted.used_medicines.strip()
        allergy = extracted.allergy_or_contraindication.strip()
        return bool(
            used
            and allergy
            and used != "不确定"
            and allergy != "不确定"
        )

    @staticmethod
    def _has_meaningful_complaint(extracted: InquiryExtractedInformation) -> bool:
        if extracted.case_summary.strip():
            return True
        return any(
            item.status == "present" and bool(item.evidence.strip())
            for item in extracted.observations
        )

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
        observation_map = {item.concept: item for item in current.observations}
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
        return InquiryExtractedInformation(
            case_summary=interpretation.case_summary or current.case_summary,
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
            clarification_answers={},
            asked_clarifications=[],
            pending_clarification="",
            symptoms_text=InquiryOrchestrator._chief_complaint(
                observations,
                current.symptoms_text,
                transcript,
            ),
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
    def _chief_complaint(observations, current: str, transcript: str) -> str:
        for observation in observations:
            if observation.status != "present":
                continue
            concept = " ".join(str(observation.concept or "").split()).strip()
            if concept:
                for separator in ("、", "；", "，", ","):
                    concept = concept.split(separator, 1)[0]
                return concept[:24]

        fallback = str(current or transcript or "").strip()
        for separator in ("、", "；", "，", "。", ",", ".", "！", "？"):
            fallback = fallback.split(separator, 1)[0]
        for prefix in ("我感觉", "我觉得", "我有一点", "我有点", "有一点", "有点"):
            if fallback.startswith(prefix):
                fallback = fallback[len(prefix) :].strip()
                break
        return fallback[:24]

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
