from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.schemas.inquiry import (  # noqa: E402
    InquiryExtractedInformation,
    InquiryInformationRevisionRequest,
    InquirySessionCreateRequest,
    InquiryTreatmentConfirmRequest,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from app.schemas.dispense import DispenseConfirmResponse  # noqa: E402
from app.services.dispense_service import DispenseError  # noqa: E402
from app.services.inquiry_orchestrator import InquiryOrchestrator  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.symptom_interpreter import SymptomInterpretation, SymptomInterpreter  # noqa: E402


class FakeInterpreter:
    def __init__(self, results: list[SymptomInterpretation]) -> None:
        self.results = list(results)

    def interpret(self, *_args, **_kwargs) -> SymptomInterpretation:
        if self.results:
            return self.results.pop(0)
        return SymptomInterpretation(source="rules_fallback")


class FakeOpeningInterpreter(FakeInterpreter):
    def opening_question(self, profile, fallback):
        return f"{profile['name']}，今天感觉怎么样？哪里最不舒服？", "cloud"


class CapturingInterpreter(FakeInterpreter):
    def __init__(self, results: list[SymptomInterpretation]) -> None:
        super().__init__(results)
        self.contexts = []

    def interpret(self, _transcript, existing, _profile) -> SymptomInterpretation:
        self.contexts.append(existing)
        return super().interpret()


class RecommendationInterpreter(FakeInterpreter):
    def explain_recommendation(self, _context):
        return {
            "ok": True,
            "source": "cloud",
            "summary": "你目前主要是喉咙疼和干咳，现有信息更适合先照顾咽喉不适。",
            "option_reasons": {
                "A": "银黄颗粒更贴近这次咽喉疼和干咳，作为当前首选更直接。",
                "B": "如果咳嗽感更突出，可对照这一方案的适用说明再选择。",
            },
        }


class UnavailableAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {"ok": False}


class FakeDispenseService:
    def __init__(self, fail_at: int | None = None) -> None:
        self.requests = []
        self.fail_at = fail_at

    def confirm(self, request):
        self.requests.append(request)
        if self.fail_at == len(self.requests):
            return DispenseConfirmResponse(
                ok=False,
                dry_run=False,
                message="外设开柜失败",
                record_id=f"record-{len(self.requests)}",
            )
        return DispenseConfirmResponse(
            ok=True,
            dry_run=False,
            message=f"{request.slot}号柜门已打开。",
            record_id=f"record-{len(self.requests)}",
        )


class FakeGuestArchiveService:
    def __init__(self) -> None:
        self.requests = []

    def schedule_capture(self, session_id: str, guest_name: str) -> None:
        self.requests.append((session_id, guest_name))


class InquiryOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "inquiry.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def create_session(
        self,
        interpreter: FakeInterpreter | None = None,
        dispense_service: FakeDispenseService | None = None,
        guest_archive_service: FakeGuestArchiveService | None = None,
    ):
        service = InquiryOrchestrator(
            interpreter=interpreter or FakeInterpreter([]),
            dispense_service=dispense_service,
            guest_archive_service=guest_archive_service,
        )
        session = service.create_session(InquirySessionCreateRequest(service_user_id="zhangsan"))
        return service, session

    def test_registered_identity_is_confirmed_once_per_session(self) -> None:
        service, session = self.create_session()

        self.assertEqual(session.user_name, "张三")
        self.assertEqual(session.stage, "symptoms")
        self.assertEqual(session.next_action, "ask")
        self.assertIn("今天哪里不舒服", session.reply)
        self.assertIn("慢慢说", session.reply)
        self.assertNotIn("我已经读取你的基础信息", session.reply)

        restored = service.get_session(session.session_id)
        self.assertEqual(restored.user_name, "张三")
        self.assertEqual(restored.messages[0].role, "assistant")
        self.assertNotIn("确认姓名", restored.reply)

    def test_guest_session_schedules_a_background_identity_photo(self) -> None:
        archive = FakeGuestArchiveService()
        service = InquiryOrchestrator(
            interpreter=FakeInterpreter([]),
            dispense_service=FakeDispenseService(),
            guest_archive_service=archive,
        )

        session = service.create_session(InquirySessionCreateRequest(guest_name="访客"))

        self.assertEqual(archive.requests, [(session.session_id, "访客")])
        self.assertIn("今天哪里不舒服", session.reply)

    def test_cloud_opening_can_replace_the_fallback_without_controlling_session_state(self) -> None:
        service = InquiryOrchestrator(
            interpreter=FakeOpeningInterpreter([]),
            guest_archive_service=FakeGuestArchiveService(),
        )

        session = service.create_session(InquirySessionCreateRequest(service_user_id="zhangsan"))

        self.assertEqual(session.reply, "张三，今天感觉怎么样？哪里最不舒服？")
        self.assertEqual(session.source, "cloud")
        self.assertEqual(session.stage, "symptoms")
        self.assertEqual(session.next_action, "ask")

    def test_distinct_symptoms_reach_distinct_otc_medicines(self) -> None:
        knowledge = MedicineKnowledgeRepository()
        examples = [
            (["感冒鼻部症状"], ["清稀鼻涕"], "slot-03-ganmao-qingre"),
            (["咳嗽咳痰"], ["干咳"], "slot-05-nin-jiom-pei-pa-koa"),
            (["咽喉口腔不适"], ["口腔溃疡"], "slot-11-guilin-xiguashuang"),
            (["恶心暑湿"], ["恶心呕吐"], "slot-08-huoxiang-zhengqi"),
            (["腹泻肠道不适"], ["腹泻"], "slot-09-bifid-triple"),
            (["便秘"], ["便秘"], "slot-06-lactulose"),
            (["胃酸胃部不适"], ["反酸烧心"], "slot-12-hydrotalcite"),
            (["皮肤真菌不适"], [], "slot-16-ketoconazole"),
            (["肌肉关节疼痛"], ["肌肉关节疼痛"], "slot-19-ketoprofen-gel"),
            (["干眼不适"], ["眼干眼涩"], "slot-13-sodium-hyaluronate-eye"),
            (["鼻炎过敏"], ["鼻痒喷嚏"], "slot-18-budesonide-nasal"),
            (["营养补充"], [], "slot-02-centrum"),
        ]

        selected = []
        for dimensions, features, expected_id in examples:
            options = knowledge.treatment_options(
                dimensions,
                "头孢过敏",
                symptom_features=features,
            )
            self.assertTrue(options, dimensions)
            actual_id = options[0].medicines[0].id
            self.assertEqual(actual_id, expected_id, dimensions)
            selected.append(actual_id)

        self.assertGreaterEqual(len(set(selected)), 10)

    def test_model_can_choose_the_most_useful_next_question(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["感冒鼻部症状"],
                    dimension_evidence={"感冒鼻部症状": "流鼻涕"},
                    follow_up_question="有没有药物过敏？",
                    confidence=0.9,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)

        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我有点流鼻涕"))

        self.assertEqual(result.stage, "allergies")
        self.assertEqual(result.reply, "有没有药物过敏？")
        self.assertEqual(result.source, "cloud")

    def test_model_worded_follow_up_is_used_when_it_matches_the_required_field(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["便秘"],
                    dimension_evidence={"便秘": "排便困难"},
                    follow_up_question="排便困难持续多久了，是今天才有还是已经好几天？",
                    confidence=0.9,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)

        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="最近排便困难"))

        self.assertEqual(result.stage, "duration")
        self.assertEqual(result.reply, "排便困难持续多久了，是今天才有还是已经好几天？")
        self.assertEqual(result.source, "cloud")

    def test_model_can_continue_one_material_followup_after_core_facts_are_complete(self) -> None:
        repeated = [
            SymptomInterpretation(
                symptom_dimensions=["便秘"],
                dimension_evidence={"便秘": "排便困难"},
                duration="一天",
                used_medicines="未使用",
                allergy_or_contraindication="无",
                follow_up_question=question,
                action_intent="ask",
                confidence=0.9,
                source="cloud",
            )
            for question in ("大便是否干硬？", "大概几天一次？", "最近饮水怎么样？")
        ]
        service, session = self.create_session(FakeInterpreter(repeated))

        first = service.process_turn(session.session_id, InquiryTurnRequest(transcript="排便困难一天了"))
        second = service.process_turn(session.session_id, InquiryTurnRequest(transcript="大便有点干硬"))
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="大概两天一次"))

        self.assertEqual(first.reply, "大便是否干硬？")
        self.assertEqual(second.reply, "大概几天一次？")
        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertEqual(result.reply, "最近饮水怎么样？")

    def test_model_does_not_repeat_a_question_the_user_already_answered(self) -> None:
        repeated_reply = "好的，伤口没有红肿或渗液。请问伤口有没有红肿或渗液？"
        service, session = self.create_session(
            FakeInterpreter(
                [
                    SymptomInterpretation(
                        symptom_dimensions=["轻微外伤"],
                        dimension_evidence={"轻微外伤": "膝盖擦伤"},
                        symptom_features=["皮肤破损"],
                        duration="刚刚",
                        used_medicines="未使用",
                        allergy_or_contraindication="无",
                        follow_up_question="伤口有没有红肿或渗液？",
                        assistant_reply=repeated_reply,
                        action_intent="ask",
                        confidence=0.9,
                        source="cloud",
                    ),
                    SymptomInterpretation(
                        symptom_dimensions=["轻微外伤"],
                        dimension_evidence={"轻微外伤": "没有红肿或渗液"},
                        follow_up_question="伤口有没有红肿或渗液？",
                        assistant_reply=repeated_reply,
                        action_intent="ask",
                        confidence=0.9,
                        source="cloud",
                    ),
                ]
            )
        )

        first = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我刚刚膝盖擦伤了"))
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="没有红肿或渗液"))

        self.assertEqual(first.next_action, "ask")
        self.assertEqual(result.stage, "result")
        self.assertNotEqual(result.reply, repeated_reply)

    def test_model_receives_the_complete_prior_conversation(self) -> None:
        interpreter = CapturingInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["便秘"],
                    dimension_evidence={"便秘": "排便困难"},
                    follow_up_question=f"继续确认第{index}项？",
                    assistant_reply=f"我记下了。继续确认第{index}项？",
                    action_intent="ask",
                    confidence=0.8,
                    source="cloud",
                )
                for index in range(1, 9)
            ]
        )
        service, session = self.create_session(interpreter)
        for index in range(1, 8):
            service.process_turn(session.session_id, InquiryTurnRequest(transcript=f"补充信息{index}"))

        service.process_turn(session.session_id, InquiryTurnRequest(transcript="最后一项补充"))

        conversation = interpreter.contexts[-1]["conversation"]
        self.assertGreater(len(conversation), 12)
        self.assertEqual(conversation[0]["role"], "assistant")
        self.assertIn("今天哪里不舒服", conversation[0]["content"])

    def test_ai_writes_natural_reasons_without_changing_safe_options(self) -> None:
        interpreter = RecommendationInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["咽喉口腔不适"],
                    dimension_evidence={"咽喉口腔不适": "喉咙疼"},
                    symptom_features=["咽喉疼痛"],
                    duration="两天",
                    used_medicines="未使用",
                    allergy_or_contraindication="头孢过敏",
                    action_intent="analyze",
                    confidence=0.92,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="喉咙疼两天了，没吃药"),
        )

        self.assertGreaterEqual(len(result.treatment_options), 1)
        self.assertIn("更贴近", result.treatment_options[0].when)
        self.assertNotIn("优先覆盖", result.treatment_options[0].when)
        self.assertTrue(result.reasoning_summary.startswith("你目前主要是"))

    def test_review_revision_replaces_facts_and_recomputes_recommendation_once(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["便秘"],
                    dimension_evidence={"便秘": "排便困难"},
                    symptom_features=["便秘"],
                    duration="一天",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    action_intent="analyze",
                    confidence=0.91,
                    source="cloud",
                ),
                SymptomInterpretation(
                    symptom_dimensions=["胃酸胃部不适"],
                    dimension_evidence={"胃酸胃部不适": "反酸烧心"},
                    symptom_features=["反酸烧心"],
                    reasoning_summary="你描述的是反酸烧心，持续半天，目前还没有用药。",
                    action_intent="analyze",
                    confidence=0.93,
                    source="cloud",
                ),
            ]
        )
        service, session = self.create_session(interpreter)
        original = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="排便困难一天了，还没有用药，也没有过敏"),
        )
        self.assertEqual(original.primary_candidate.id, "slot-06-lactulose")

        revised = service.revise_information(
            session.session_id,
            InquiryInformationRevisionRequest(
                main_complaint="反酸烧心",
                duration="半天",
                used_medicines="未使用",
                allergy_or_contraindication="头孢过敏",
                finalize=True,
            ),
        )

        self.assertEqual(revised.stage, "result")
        self.assertEqual(revised.extracted_information.symptoms_text, "反酸烧心")
        self.assertEqual(revised.extracted_information.duration, "半天")
        self.assertEqual(revised.extracted_information.allergy_or_contraindication, "头孢过敏")
        self.assertEqual(revised.primary_candidate.id, "slot-12-hydrotalcite")
        self.assertEqual(revised.action_status, "ready")

    def test_old_age_alone_does_not_raise_risk(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["感冒鼻部症状"],
                    dimension_evidence={"感冒鼻部症状": "流鼻涕"},
                    symptom_features=["清稀鼻涕"],
                    feature_evidence={"清稀鼻涕": "流清鼻涕"},
                    duration="刚开始",
                    used_medicines="未使用",
                    allergy_or_contraindication="头孢过敏",
                    confidence=0.92,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我刚开始流清鼻涕，还没吃药"))

        self.assertEqual(result.risk_level, "low")
        self.assertEqual(result.next_action, "show_recommendation")
        self.assertIsNotNone(result.primary_candidate)
        self.assertNotEqual(result.primary_candidate.id, "slot-04-amoxicillin")

    def test_medium_dizziness_can_offer_reviewed_otc_after_core_vitals(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["恶心暑湿"],
                    dimension_evidence={"恶心暑湿": "中暑头晕"},
                    duration="半天",
                    used_medicines="未使用",
                    allergy_or_contraindication="头孢过敏",
                    confidence=0.86,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)
        pending = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我中暑头晕半天了，还没吃药"))

        self.assertEqual(pending.next_action, "measure_vitals")

        result = service.attach_vitals(
            session.session_id,
            InquiryVitalsRequest(temperature=36.6, heart_rate=76, spo2=98, measured_at="2026-07-18 09:00:00"),
        )

        self.assertEqual(result.risk_level, "medium")
        self.assertEqual(result.next_action, "show_recommendation")
        self.assertEqual(result.primary_candidate.id, "slot-08-huoxiang-zhengqi")
        self.assertIn("解表化湿", result.primary_candidate.indications)
        self.assertIn("一次1丸", result.primary_candidate.dosage)
        self.assertTrue(result.can_view_medicines)
        self.assertEqual(result.vitals["temperature"], 36.6)
        self.assertTrue(any("额温 36.6" in reason and "血氧 98" in reason for reason in result.risk_reasons))

    def test_short_context_answers_advance_without_repeating_questions(self) -> None:
        service = InquiryOrchestrator(
            interpreter=SymptomInterpreter(ai_service=UnavailableAiService()),
            dispense_service=FakeDispenseService(),
        )
        session = service.create_session(InquirySessionCreateRequest(guest_name="访客"))

        duration = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我有点胃痛"))
        used = service.process_turn(session.session_id, InquiryTurnRequest(transcript="五分钟"))
        allergies = service.process_turn(session.session_id, InquiryTurnRequest(transcript="还没有"))
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="没有"))

        self.assertEqual(duration.stage, "duration")
        self.assertEqual(used.stage, "used_medicines")
        self.assertEqual(allergies.stage, "allergies")
        self.assertEqual(result.next_action, "show_recommendation")
        self.assertEqual(result.extracted_information.duration, "五分钟")
        self.assertEqual(result.extracted_information.used_medicines, "未使用")
        self.assertEqual(result.extracted_information.allergy_or_contraindication, "无")

    def test_invalid_asr_text_does_not_resolve_a_structured_clarification(self) -> None:
        service = InquiryOrchestrator(
            interpreter=SymptomInterpreter(ai_service=UnavailableAiService()),
            dispense_service=FakeDispenseService(),
        )
        session = service.create_session(InquirySessionCreateRequest(guest_name="访客"))
        clarification = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我感冒流鼻涕"))
        retry = service.process_turn(session.session_id, InquiryTurnRequest(transcript="蝗虫"))

        self.assertEqual(clarification.extracted_information.pending_clarification, "nasal_discharge")
        self.assertEqual(retry.extracted_information.pending_clarification, "nasal_discharge")
        self.assertNotIn("nasal_discharge", retry.extracted_information.clarification_answers)
        self.assertIn("清稀", retry.reply)

    def test_chest_tightness_and_shortness_of_breath_are_escalated_immediately(self) -> None:
        service = InquiryOrchestrator(
            interpreter=SymptomInterpreter(ai_service=UnavailableAiService()),
            dispense_service=FakeDispenseService(),
        )
        session = service.create_session(InquirySessionCreateRequest(guest_name="访客"))
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我胸闷气短"))

        self.assertIn(result.risk_level, {"high", "emergency"})
        self.assertEqual(result.next_action, "escalate")
        self.assertFalse(result.can_view_medicines)

    def test_explicit_vitals_request_interrupts_missing_field_order_and_then_resumes(self) -> None:
        service = InquiryOrchestrator(
            interpreter=SymptomInterpreter(ai_service=UnavailableAiService()),
            dispense_service=FakeDispenseService(),
        )
        session = service.create_session(InquirySessionCreateRequest(guest_name="访客"))

        pending = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我头晕，现在先测一下身体体征"),
        )

        self.assertEqual(pending.next_action, "measure_vitals")
        self.assertEqual(pending.stage, "vitals")

        resumed = service.attach_vitals(
            session.session_id,
            InquiryVitalsRequest(temperature=36.6, heart_rate=76, spo2=98, measured_at="2026-07-18 09:00:00"),
        )

        self.assertEqual(resumed.next_action, "ask")
        self.assertEqual(resumed.stage, "clarification")
        self.assertIn("恶心呕吐", resumed.reply)
        self.assertEqual(resumed.vitals["spo2"], 98)

        duration = service.process_turn(session.session_id, InquiryTurnRequest(transcript="没有恶心、呕吐或腹泻"))
        self.assertEqual(duration.stage, "duration")
        self.assertIn("开始", duration.reply)

    def test_model_can_request_vitals_before_duration_and_resume_after_measurement(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["轻微外伤"],
                    dimension_evidence={"轻微外伤": "擦伤"},
                    action_intent="measure_vitals",
                    action_reason="用户同时描述明显乏力",
                    confidence=0.8,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)

        pending = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我擦伤了，而且很乏力"))
        resumed = service.attach_vitals(
            session.session_id,
            InquiryVitalsRequest(temperature=36.7, heart_rate=74, spo2=98, measured_at="2026-07-18 09:00:00"),
        )

        self.assertEqual(pending.next_action, "measure_vitals")
        self.assertEqual(resumed.stage, "duration")
        self.assertEqual(resumed.next_action, "ask")

    def test_historical_relative_duration_advances_instead_of_repeating_the_same_question(self) -> None:
        service = InquiryOrchestrator(
            interpreter=SymptomInterpreter(ai_service=UnavailableAiService()),
            dispense_service=FakeDispenseService(),
        )
        session = service.create_session(InquirySessionCreateRequest(guest_name="访客"))

        duration = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我有点胃痛"))
        next_step = service.process_turn(session.session_id, InquiryTurnRequest(transcript="去年"))

        self.assertEqual(duration.stage, "duration")
        self.assertEqual(next_step.stage, "used_medicines")
        self.assertEqual(next_step.extracted_information.duration, "去年")
        self.assertNotEqual(next_step.reply, duration.reply)

    def test_unclear_answer_rephrases_instead_of_repeating_the_identical_prompt(self) -> None:
        service = InquiryOrchestrator(
            interpreter=SymptomInterpreter(ai_service=UnavailableAiService()),
            dispense_service=FakeDispenseService(),
        )
        session = service.create_session(InquirySessionCreateRequest(guest_name="访客"))

        first = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我有点胃痛"))
        second = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我说不清"))

        self.assertEqual(first.stage, "duration")
        self.assertEqual(second.stage, "duration")
        self.assertNotEqual(second.reply, first.reply)
        self.assertIn("刚开始", second.reply)

    def test_nasal_clarification_changes_primary_candidate(self) -> None:
        service = InquiryOrchestrator(
            interpreter=SymptomInterpreter(ai_service=UnavailableAiService()),
            dispense_service=FakeDispenseService(),
        )
        session = service.create_session(InquirySessionCreateRequest(service_user_id="zhangsan"))

        clarification = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我鼻塞而且流鼻涕"),
        )
        self.assertEqual(clarification.stage, "clarification")
        self.assertIn("清稀鼻涕", clarification.reply)

        duration = service.process_turn(session.session_id, InquiryTurnRequest(transcript="是清稀鼻涕"))
        used = service.process_turn(session.session_id, InquiryTurnRequest(transcript="今天开始"))
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="这次还没吃药"))

        self.assertEqual(duration.stage, "duration")
        self.assertEqual(used.stage, "used_medicines")
        self.assertEqual(result.primary_candidate.id, "slot-03-ganmao-qingre")
        self.assertIn("清稀鼻涕", result.extracted_information.symptom_features)

    def test_similar_history_prompts_for_change_before_reusing_history_as_tie_breaker(self) -> None:
        service, prior = self.create_session()
        prior.extracted_information = InquiryExtractedInformation(
            symptom_dimensions=["感冒鼻部症状"],
            dimension_evidence={"感冒鼻部症状": "流清鼻涕"},
            symptom_features=["清稀鼻涕"],
            duration="一天",
            used_medicines="未使用",
            allergy_or_contraindication="头孢过敏",
            confidence=0.9,
        )
        prior.risk_level = "low"
        prior.selected_option_id = "A"
        prior.action_status = "complete"
        prior.action_items = [{"medicine_id": "slot-03-ganmao-qingre", "ok": True}]
        prior.title = "张三 · 鼻塞流涕"
        service.repository.save_session(prior)
        service.interpreter = SymptomInterpreter(ai_service=UnavailableAiService())

        current = service.create_session(InquirySessionCreateRequest(service_user_id="zhangsan"))
        comparison = service.process_turn(
            current.session_id,
            InquiryTurnRequest(transcript="我又有点鼻塞流鼻涕"),
        )

        self.assertEqual(comparison.stage, "clarification")
        self.assertEqual(comparison.extracted_information.pending_clarification, "history_change")
        self.assertIn("上次", comparison.reply)

        next_question = service.process_turn(current.session_id, InquiryTurnRequest(transcript="比上次轻一些"))
        self.assertEqual(next_question.extracted_information.clarification_answers["history_change"], "比上次轻一些")
        self.assertEqual(next_question.extracted_information.pending_clarification, "nasal_discharge")

    def test_current_features_dominate_and_history_only_breaks_close_candidate_scores(self) -> None:
        knowledge = MedicineKnowledgeRepository()

        clear_plan = knowledge.treatment_options(
            ["感冒鼻部症状"],
            "无",
            symptom_features=["清稀鼻涕"],
        )[0]
        yellow_plan = knowledge.treatment_options(
            ["感冒鼻部症状"],
            "无",
            symptom_features=["黄稠鼻涕"],
        )[0]
        historical_tie_break = knowledge.treatment_options(
            ["发热全身不适"],
            "无",
            history_medicine_counts={"slot-03-ganmao-qingre": 1},
        )[0]

        self.assertEqual(clear_plan.medicines[0].id, "slot-03-ganmao-qingre")
        self.assertEqual(yellow_plan.medicines[0].id, "slot-01-fufang-ganmaoling")
        self.assertEqual(historical_tie_break.medicines[0].id, "slot-03-ganmao-qingre")

    def test_three_medicine_wound_plan_opens_exactly_one_cabinet_per_request(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["轻微外伤"],
                    dimension_evidence={"轻微外伤": "擦伤破皮"},
                    symptom_features=["皮肤破损"],
                    feature_evidence={"皮肤破损": "破皮"},
                    duration="刚开始",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    action_intent="analyze",
                    confidence=0.92,
                    source="cloud",
                )
            ]
        )
        dispense = FakeDispenseService()
        service, session = self.create_session(interpreter, dispense)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚才擦伤破皮，还没用药，没有过敏"),
        )
        selected = result.treatment_options[0]
        self.assertEqual(len(selected.medicines), 3)

        responses = []
        for index in range(3):
            responses.append(
                service.confirm_treatment(
                    result.session_id,
                    InquiryTreatmentConfirmRequest(
                        option_id=selected.option_id,
                        confirmed_safety_notice=True,
                        expected_item_index=index,
                    ),
                )
            )
            self.assertEqual(len(dispense.requests), index + 1)

        self.assertEqual([response.status for response in responses], ["opening", "opening", "complete"])
        self.assertEqual(responses[-1].completed_count, 3)
        self.assertEqual([request.medicine_id for request in dispense.requests], [
            medicine.id for medicine in selected.medicines
        ])

    def test_high_spo2_risk_blocks_candidates(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["咳嗽咳痰"],
                    dimension_evidence={"咳嗽咳痰": "咳嗽"},
                    duration="一天",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    confidence=0.9,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)
        pending = service.process_turn(session.session_id, InquiryTurnRequest(transcript="咳嗽一天了，没有吃药，也没有过敏"))
        self.assertEqual(pending.next_action, "measure_vitals")

        result = service.attach_vitals(
            session.session_id,
            InquiryVitalsRequest(temperature=37.1, heart_rate=88, spo2=92, measured_at="2026-07-18 09:00:00"),
        )

        self.assertEqual(result.risk_level, "high")
        self.assertEqual(result.next_action, "escalate")
        self.assertIsNone(result.primary_candidate)
        self.assertIsNone(result.alternative_candidate)
        self.assertFalse(result.can_view_medicines)

    def test_emergency_terms_short_circuit_model_and_recommendation(self) -> None:
        service, session = self.create_session()
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我胸痛而且呼吸困难"))

        self.assertEqual(result.risk_level, "emergency")
        self.assertEqual(result.next_action, "escalate")
        self.assertIsNone(result.primary_candidate)

    def test_negated_emergency_terms_do_not_escalate(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["恶心暑湿"],
                    dimension_evidence={"恶心暑湿": "轻微头晕"},
                    duration="刚开始",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    confidence=0.88,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我轻微头晕，没有胸痛，也没有呼吸困难"),
        )

        self.assertNotEqual(result.risk_level, "emergency")
        self.assertEqual(result.next_action, "measure_vitals")

    def test_direct_allergy_term_excludes_conflicting_candidate(self) -> None:
        knowledge = MedicineKnowledgeRepository()
        medicine = knowledge.medicine_repository.get_by_id("slot-18-budesonide-nasal")

        self.assertIsNotNone(medicine)
        self.assertFalse(knowledge._eligible(medicine, "布地奈德过敏"))
        self.assertTrue(knowledge._eligible(medicine, "无"))

    def test_non_otc_and_chronic_inventory_is_not_used_by_inquiry_recommendations(self) -> None:
        knowledge = MedicineKnowledgeRepository()

        respiratory = knowledge.candidates(["发热全身不适", "咽喉口腔不适"], "无")
        allergy = knowledge.candidates(["过敏瘙痒"], "无")
        chronic = knowledge.candidates(["慢病既往用药"], "无")

        self.assertNotIn("slot-14-oseltamivir", {candidate.id for candidate in respiratory})
        self.assertNotIn("slot-04-amoxicillin", {candidate.id for candidate in respiratory})
        self.assertNotIn("slot-23-desloratadine", {candidate.id for candidate in allergy})
        self.assertEqual(chronic, [])

    def test_at_most_one_optional_alternative_is_returned_for_ambiguous_evidence(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["感冒鼻部症状", "发热全身不适"],
                    dimension_evidence={"感冒鼻部症状": "鼻塞", "发热全身不适": "头痛"},
                    symptom_features=["清稀鼻涕", "明显畏寒"],
                    feature_evidence={"清稀鼻涕": "清鼻涕", "明显畏寒": "怕冷"},
                    duration="刚开始",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    confidence=0.58,
                    source="local_llm",
                )
            ]
        )
        service, session = self.create_session(interpreter)
        pending = service.process_turn(session.session_id, InquiryTurnRequest(transcript="刚开始鼻塞头痛，没有吃药，也没有过敏"))
        result = service.attach_vitals(
            session.session_id,
            InquiryVitalsRequest(temperature=36.8, heart_rate=75, spo2=98, measured_at="2026-07-18 09:00:00"),
        ) if pending.next_action == "measure_vitals" else pending

        self.assertIsNotNone(result.primary_candidate)
        self.assertIsNotNone(result.alternative_candidate)
        self.assertNotEqual(result.primary_candidate.id, result.alternative_candidate.id)
        self.assertLessEqual(len(result.treatment_options), 2)

    def test_knowledge_repository_never_returns_more_than_two_options_by_default(self) -> None:
        options = MedicineKnowledgeRepository().treatment_options(
            ["感冒鼻部症状", "发热全身不适", "咳嗽咳痰", "咽喉口腔不适"],
            "头孢过敏",
            symptom_features=["清稀鼻涕", "干咳", "咽喉疼痛"],
        )

        self.assertGreaterEqual(len(options), 1)
        self.assertLessEqual(len(options), 2)

    def test_model_action_intent_can_request_vitals_for_a_non_default_dimension(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["轻微外伤"],
                    dimension_evidence={"轻微外伤": "擦伤"},
                    duration="刚开始",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    reasoning_summary="需要用核心体征排除全身异常。",
                    action_intent="measure_vitals",
                    action_reason="用户同时描述了明显乏力",
                    confidence=0.84,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚开始有轻微擦伤，还没用药，没有过敏"),
        )

        self.assertEqual(result.next_action, "measure_vitals")
        self.assertEqual(result.model_action_intent, "measure_vitals")
        self.assertEqual(result.reasoning_summary, "需要用核心体征排除全身异常。")

    def test_selected_treatment_option_only_opens_its_medicines_once(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["咳嗽咳痰", "咽喉口腔不适"],
                    dimension_evidence={"咳嗽咳痰": "咳嗽", "咽喉口腔不适": "喉咙痛"},
                    symptom_features=["干咳", "咽喉疼痛"],
                    feature_evidence={"干咳": "干咳", "咽喉疼痛": "喉咙痛"},
                    duration="一天",
                    used_medicines="未使用",
                    allergy_or_contraindication="头孢过敏",
                    action_intent="measure_vitals",
                    action_reason="核心体征会影响呼吸道症状的安全核验",
                    confidence=0.82,
                    source="cloud",
                )
            ]
        )
        dispense = FakeDispenseService()
        service, session = self.create_session(interpreter, dispense)
        pending = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="咳嗽并且喉咙痛一天了，还没用药，头孢过敏"),
        )
        result = service.attach_vitals(
            pending.session_id,
            InquiryVitalsRequest(temperature=36.7, heart_rate=78, spo2=98),
        )

        self.assertGreaterEqual(len(result.treatment_options), 1)
        selected = max(result.treatment_options, key=lambda option: len(option.medicines))
        selected_ids = [medicine.id for medicine in selected.medicines]
        self.assertGreaterEqual(len(selected_ids), 1)

        confirmed = None
        for item_index in range(len(selected_ids)):
            confirmed = service.confirm_treatment(
                result.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=selected.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=item_index,
                ),
            )
            self.assertEqual(len(dispense.requests), item_index + 1)
            expected_status = "complete" if item_index == len(selected_ids) - 1 else "opening"
            self.assertEqual(confirmed.status, expected_status)

        self.assertIsNotNone(confirmed)
        self.assertTrue(confirmed.ok)
        self.assertEqual(confirmed.completed_count, len(selected_ids))
        self.assertEqual([request.medicine_id for request in dispense.requests], selected_ids)
        self.assertTrue(all(request.confirm_real_dispense for request in dispense.requests))
        with self.assertRaises(DispenseError):
            service.confirm_treatment(
                result.session_id,
                InquiryTreatmentConfirmRequest(option_id=selected.option_id, confirmed_safety_notice=True),
            )

    def test_treatment_requires_explicit_confirmation(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["便秘"],
                    dimension_evidence={"便秘": "便秘"},
                    duration="一天",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    action_intent="analyze",
                    confidence=0.9,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter, FakeDispenseService())
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="便秘一天了，没有用药，没有过敏"),
        )

        self.assertEqual(result.action_status, "ready")
        with self.assertRaises(DispenseError):
            service.confirm_treatment(
                result.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=result.treatment_options[0].option_id,
                    confirmed_safety_notice=False,
                ),
            )

    def test_inventory_change_invalidates_displayed_option_before_opening(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["感冒鼻部症状"],
                    dimension_evidence={"感冒鼻部症状": "鼻塞"},
                    symptom_features=["清稀鼻涕"],
                    feature_evidence={"清稀鼻涕": "清鼻涕"},
                    duration="刚开始",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    action_intent="analyze",
                    confidence=0.9,
                    source="cloud",
                )
            ]
        )
        dispense = FakeDispenseService()
        service, session = self.create_session(interpreter, dispense)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚开始鼻塞，没有用药，没有过敏"),
        )
        selected = result.treatment_options[0]
        with db.connect() as conn:
            conn.execute("UPDATE medicines SET stock=0 WHERE id=?", (selected.medicines[0].id,))

        with self.assertRaises(DispenseError):
            service.confirm_treatment(
                result.session_id,
                InquiryTreatmentConfirmRequest(option_id=selected.option_id, confirmed_safety_notice=True),
            )

        self.assertEqual(dispense.requests, [])
        refreshed = service.get_session(result.session_id)
        self.assertEqual(refreshed.action_status, "ready")
        self.assertNotEqual(
            [medicine.id for medicine in selected.medicines],
            [medicine.id for medicine in refreshed.treatment_options[0].medicines],
        )

    def test_partial_open_is_terminal_and_does_not_repeat_opened_cabinet(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["轻微外伤"],
                    dimension_evidence={"轻微外伤": "擦伤破皮"},
                    symptom_features=["皮肤破损"],
                    feature_evidence={"皮肤破损": "破皮"},
                    duration="一天",
                    used_medicines="未使用",
                    allergy_or_contraindication="无",
                    action_intent="measure_vitals",
                    confidence=0.85,
                    source="cloud",
                )
            ]
        )
        dispense = FakeDispenseService(fail_at=2)
        service, session = self.create_session(interpreter, dispense)
        pending = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="擦伤破皮一天，没有用药，没有过敏"),
        )
        result = service.attach_vitals(
            pending.session_id,
            InquiryVitalsRequest(temperature=36.7, heart_rate=78, spo2=98),
        )
        selected = result.treatment_options[0]

        first = service.confirm_treatment(
            result.session_id,
            InquiryTreatmentConfirmRequest(
                option_id=selected.option_id,
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )
        confirmed = service.confirm_treatment(
            result.session_id,
            InquiryTreatmentConfirmRequest(
                option_id=selected.option_id,
                confirmed_safety_notice=True,
                expected_item_index=1,
            ),
        )

        self.assertEqual(first.status, "opening")
        self.assertFalse(confirmed.ok)
        self.assertEqual(confirmed.status, "partial")
        self.assertEqual(len(dispense.requests), 2)
        with self.assertRaises(DispenseError):
            service.confirm_treatment(
                result.session_id,
                InquiryTreatmentConfirmRequest(option_id=selected.option_id, confirmed_safety_notice=True),
            )
        self.assertEqual(len(dispense.requests), 2)


if __name__ == "__main__":
    unittest.main()
