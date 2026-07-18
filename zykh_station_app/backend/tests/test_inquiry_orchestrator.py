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
    InquirySessionCreateRequest,
    InquiryTreatmentConfirmRequest,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from app.schemas.dispense import DispenseConfirmResponse  # noqa: E402
from app.services.dispense_service import DispenseError  # noqa: E402
from app.services.inquiry_orchestrator import InquiryOrchestrator  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.symptom_interpreter import SymptomInterpretation  # noqa: E402


class FakeInterpreter:
    def __init__(self, results: list[SymptomInterpretation]) -> None:
        self.results = list(results)

    def interpret(self, *_args, **_kwargs) -> SymptomInterpretation:
        if self.results:
            return self.results.pop(0)
        return SymptomInterpretation(source="rules_fallback")


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
    ):
        service = InquiryOrchestrator(
            interpreter=interpreter or FakeInterpreter([]),
            dispense_service=dispense_service,
        )
        session = service.create_session(InquirySessionCreateRequest(service_user_id="zhangsan"))
        return service, session

    def test_registered_identity_is_confirmed_once_per_session(self) -> None:
        service, session = self.create_session()

        self.assertEqual(session.user_name, "张三")
        self.assertEqual(session.stage, "symptoms")
        self.assertEqual(session.next_action, "ask")

        restored = service.get_session(session.session_id)
        self.assertEqual(restored.user_name, "张三")
        self.assertEqual(restored.messages[0].role, "assistant")
        self.assertNotIn("确认姓名", restored.reply)

    def test_model_follow_up_cannot_skip_the_current_missing_field(self) -> None:
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

        self.assertEqual(result.stage, "duration")
        self.assertIn("持续多久", result.reply)
        self.assertNotIn("过敏", result.reply)

    def test_old_age_alone_does_not_raise_risk(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["感冒鼻部症状"],
                    dimension_evidence={"感冒鼻部症状": "流鼻涕"},
                    duration="刚开始",
                    used_medicines="未使用",
                    allergy_or_contraindication="头孢过敏",
                    confidence=0.92,
                    source="cloud",
                )
            ]
        )
        service, session = self.create_session(interpreter)
        result = service.process_turn(session.session_id, InquiryTurnRequest(transcript="我刚开始流鼻涕，还没吃药"))

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
        self.assertTrue(result.can_view_medicines)

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

    def test_only_one_optional_alternative_is_returned_for_ambiguous_evidence(self) -> None:
        interpreter = FakeInterpreter(
            [
                SymptomInterpretation(
                    symptom_dimensions=["感冒鼻部症状", "发热全身不适"],
                    dimension_evidence={"感冒鼻部症状": "鼻塞", "发热全身不适": "头痛"},
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

        self.assertGreaterEqual(len(result.treatment_options), 2)
        selected = result.treatment_options[1]
        selected_ids = [medicine.id for medicine in selected.medicines]
        self.assertGreaterEqual(len(selected_ids), 2)

        confirmed = service.confirm_treatment(
            result.session_id,
            InquiryTreatmentConfirmRequest(option_id=selected.option_id, confirmed_safety_notice=True),
        )

        self.assertTrue(confirmed.ok)
        self.assertEqual(confirmed.status, "complete")
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
                    symptom_dimensions=["咳嗽咳痰", "咽喉口腔不适"],
                    dimension_evidence={"咳嗽咳痰": "咳嗽", "咽喉口腔不适": "咽痛"},
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
            InquiryTurnRequest(transcript="咳嗽咽痛一天，没有用药，没有过敏"),
        )
        result = service.attach_vitals(
            pending.session_id,
            InquiryVitalsRequest(temperature=36.7, heart_rate=78, spo2=98),
        )
        selected = result.treatment_options[0]

        confirmed = service.confirm_treatment(
            result.session_id,
            InquiryTreatmentConfirmRequest(option_id=selected.option_id, confirmed_safety_notice=True),
        )

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
