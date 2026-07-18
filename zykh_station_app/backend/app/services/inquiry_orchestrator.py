from __future__ import annotations

import threading
from uuid import uuid4

from .. import db
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.dispense import DispenseConfirmRequest
from ..schemas.inquiry import (
    InquiryExtractedInformation,
    InquirySessionCreateRequest,
    InquirySessionResponse,
    InquiryTreatmentConfirmRequest,
    InquiryTreatmentConfirmResponse,
    InquiryTreatmentDispenseItem,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from .dispense_service import DispenseError, DispenseService
from .medicine_safety_engine import MedicineSafetyEngine
from .symptom_interpreter import SymptomInterpretation, SymptomInterpreter


VITALS_DIMENSIONS = {"发热全身不适", "咳嗽咳痰", "恶心暑湿"}


class InquiryOrchestrator:
    _treatment_action_lock = threading.Lock()

    def __init__(
        self,
        repository: InquiryRepository | None = None,
        interpreter: SymptomInterpreter | None = None,
        safety_engine: MedicineSafetyEngine | None = None,
        dispense_service: DispenseService | None = None,
    ) -> None:
        self.repository = repository or InquiryRepository()
        self.interpreter = interpreter or SymptomInterpreter()
        self.safety_engine = safety_engine or MedicineSafetyEngine()
        self.dispense_service = dispense_service or DispenseService()

    def create_session(self, request: InquirySessionCreateRequest) -> InquirySessionResponse:
        user = self._load_user(request.service_user_id)
        now = db.now_text()
        user_name = str(user.get("name") or request.guest_name.strip() or "访客")
        reply = (
            f"{user_name}，我已经读取你的基础信息。请说说这次最明显的不适。"
            if user
            else "你好，我们先从这次的情况开始。请说说现在最明显的不适。"
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
        emergency = self.safety_engine.assess(
            emergency_extracted,
            session.vitals,
            self._profile_context(session),
        )
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
        self._apply_contextual_answer(session.stage, transcript, interpretation)
        extracted = self._merge_interpretation(session, transcript, interpretation)
        session.extracted_information = extracted
        session.source = interpretation.source
        session.reasoning_summary = interpretation.reasoning_summary
        session.model_action_intent = interpretation.action_intent
        session.action_reason = interpretation.action_reason

        if not session.vitals and self._should_measure_vitals_now(transcript, extracted, interpretation):
            session.stage = "vitals"
            session.next_action = "measure_vitals"
            session.reply = "这项信息现在会影响安全判断。请测量额温、心率和血氧，完成后我会接着询问尚未确认的内容。"
            self._clear_decision(session)
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
        missing = self._missing_field(session.extracted_information)
        if missing:
            self._ask_for_missing(session, missing, "")
            return self._commit(session)
        return self._finish(session, session.extracted_information, source=session.source)

    def confirm_treatment(
        self,
        session_id: str,
        request: InquiryTreatmentConfirmRequest,
    ) -> InquiryTreatmentConfirmResponse:
        if request.confirmed_safety_notice is not True:
            raise DispenseError("请先核对并确认本次方案和安全提示。")

        with self._treatment_action_lock:
            session = self._required_session(session_id)
            if session.action_status != "ready":
                raise DispenseError("本次方案已经处理或当前不可执行，请重新开始问询。", status_code=409)
            if session.risk_level not in {"low", "medium"} or not session.can_view_medicines:
                raise DispenseError("当前风险等级不允许执行开柜操作。", status_code=409)

            displayed_option = self._option(session.treatment_options, request.option_id)
            if displayed_option is None:
                raise DispenseError("未找到所选方案，请重新选择。")

            decision = self.safety_engine.assess(
                session.extracted_information,
                session.vitals,
                self._profile_context(session),
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

            session.selected_option_id = request.option_id
            session.action_status = "opening"
            session.action_message = "方案已确认，正在依次打开对应药柜。"
            session.reply = session.action_message
            self._commit(session)

            items: list[InquiryTreatmentDispenseItem] = []
            for treatment_medicine in fresh_option.medicines:
                medicine = self.safety_engine.knowledge.medicine_repository.get_by_id(treatment_medicine.id)
                if medicine is None:
                    items.append(
                        InquiryTreatmentDispenseItem(
                            medicine_id=treatment_medicine.id,
                            medicine_name=treatment_medicine.name,
                            slot=treatment_medicine.slot,
                            ok=False,
                            dry_run=False,
                            message="药品库存记录已经变化。",
                        )
                    )
                    break
                try:
                    result = self.dispense_service.confirm(
                        DispenseConfirmRequest(
                            medicine_id=medicine.id,
                            slot=medicine.slot,
                            quantity=1,
                            reason=f"AI应急问询 {session.session_id} 方案 {request.option_id}",
                            confirmed_safety_notice=True,
                            confirm_real_dispense=True,
                            target_user_id=session.user_id,
                            target_user_name=session.user_name,
                            verification_method="inquiry_confirmed",
                        )
                    )
                except DispenseError as exc:
                    items.append(
                        InquiryTreatmentDispenseItem(
                            medicine_id=medicine.id,
                            medicine_name=medicine.name,
                            slot=medicine.slot,
                            ok=False,
                            dry_run=False,
                            message=exc.message,
                        )
                    )
                    break
                items.append(
                    InquiryTreatmentDispenseItem(
                        medicine_id=medicine.id,
                        medicine_name=medicine.name,
                        slot=medicine.slot,
                        ok=result.ok,
                        dry_run=result.dry_run,
                        message=result.message,
                        record_id=result.record_id,
                    )
                )
                if not result.ok:
                    break

            succeeded = sum(1 for item in items if item.ok)
            opened = sum(1 for item in items if item.ok and not item.dry_run)
            expected = len(fresh_option.medicines)
            if succeeded == expected:
                status = "complete"
                message = (
                    f"方案 {request.option_id} 已确认，{opened} 个对应药柜已完成开柜。"
                    if opened
                    else f"方案 {request.option_id} 已完成本地测试记录，未打开柜门。"
                )
                ok = True
            elif succeeded:
                status = "partial"
                message = (
                    f"已打开 {opened} 个药柜，后续药柜未完成，请联系现场协助人员。"
                    if opened
                    else "部分本地测试记录已保存，后续操作未完成，请联系现场协助人员。"
                )
                ok = False
            else:
                status = "failed"
                message = items[-1].message if items else "开柜操作未完成，请联系现场协助人员。"
                ok = False

            session.action_status = status
            session.action_message = message
            session.reply = message
            session.next_action = "complete"
            committed = self._commit(session)
            return InquiryTreatmentConfirmResponse(
                ok=ok,
                status=status,
                option_id=request.option_id,
                message=message,
                items=items,
                session=committed,
            )

    def _finish(
        self,
        session: InquirySessionResponse,
        extracted: InquiryExtractedInformation,
        *,
        source: str,
    ) -> InquirySessionResponse:
        decision = self.safety_engine.assess(extracted, session.vitals, self._profile_context(session))
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
            option_text = f"已生成 {option_count} 个互斥方案，请只选择其中一个。" if option_count > 1 else "当前信息较明确，已生成一个优先方案。"
            session.reply = (
                f"安全核验已完成。{option_text}确认后系统才会打开方案对应药柜。"
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
            "symptoms": ("symptoms", "请再具体说说，现在哪个部位最不舒服？"),
            "duration": ("duration", "这种感觉大概从什么时候开始？"),
            "used_medicines": ("used_medicines", "这次不舒服后，有没有吃过或用过药？"),
            "allergies": ("allergies", "有没有明确过敏或不能用的药？不清楚也可以直接说。"),
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
    ) -> bool:
        explicit_request = any(
            term in transcript
            for term in ("测体征", "测一下体征", "测量体征", "读取体征", "身体体征", "量一下体温")
        )
        return bool(explicit_request or cls._requires_vitals(extracted, interpretation))

    @staticmethod
    def _profile_context(session: InquirySessionResponse) -> str:
        return "；".join(
            value.strip()
            for value in (session.user_profile, session.user_allergies)
            if value and value.strip()
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
