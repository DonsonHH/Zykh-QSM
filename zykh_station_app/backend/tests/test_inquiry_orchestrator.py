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
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
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

    def create_session(self, interpreter: FakeInterpreter | None = None):
        service = InquiryOrchestrator(interpreter=interpreter or FakeInterpreter([]))
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


if __name__ == "__main__":
    unittest.main()
