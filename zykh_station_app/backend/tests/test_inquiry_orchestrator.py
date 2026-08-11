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
from app.schemas.dispense import DispenseConfirmResponse  # noqa: E402
from app.schemas.inquiry import (  # noqa: E402
    InquiryExtractedInformation,
    InquiryInformationRevisionRequest,
    InquiryObservation,
    InquirySessionCreateRequest,
    InquiryTreatmentConfirmRequest,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from app.repositories.inquiry_repository import InquiryRepository  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.repositories.vitals_repository import VitalsRecord, VitalsRepository  # noqa: E402
from app.services.dispense_service import DispenseError  # noqa: E402
from app.services.inquiry_dialogue_policy import infer_question_topic  # noqa: E402
from app.services.inquiry_orchestrator import InquiryOrchestrator  # noqa: E402
from app.services.medicine_service import MedicineService  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402
from app.services.symptom_interpreter import SymptomInterpretation  # noqa: E402


def case(
    *,
    action: str = "ask",
    concept: str = "一般不适",
    evidence: str = "有点不舒服",
    reply: str = "请再说说最明显的变化。",
    duration: str = "",
    used: str = "",
    allergy: str = "",
    risk: str = "low",
    source: str = "cloud",
    scope_complete: bool = True,
    material_change: bool = False,
    change_type: str = "none",
    replaced_concepts: list[str] | None = None,
) -> SymptomInterpretation:
    semantic_topics: dict[str, str] = {}
    combined = f"{concept} {evidence}"
    if action == "analyze":
        if any(term in combined for term in ("头痛", "头疼")):
            semantic_topics = {
                "headache_onset": "逐渐出现",
                "headache_red_flags": "未见神经系统危险表现",
                "severity": evidence,
            }
        elif any(term in combined for term in ("中暑", "暑热", "晒后", "暑湿")):
            semantic_topics = {"exposure_trigger": evidence, "dehydration": "可以饮水"}
        elif any(term in combined for term in ("鼻塞", "打喷嚏", "流鼻涕", "咳嗽", "咳痰")):
            semantic_topics = {
                "respiratory_features": evidence,
                "breathing": "没有呼吸费力",
            }
        elif "便秘" in combined:
            semantic_topics = {"digestive_features": evidence, "severity": evidence}
        elif any(term in combined for term in ("恶心", "胃肠", "腹", "反酸")):
            semantic_topics = {"digestive_features": evidence, "severity": evidence}
        elif any(term in combined for term in ("擦伤", "伤口", "外伤", "出血")):
            semantic_topics = {"injury_features": evidence}
        else:
            semantic_topics = {"severity": evidence}
        semantic_topics.setdefault("symptom_detail", evidence)
    return SymptomInterpretation(
        case_summary=f"用户描述{evidence}。",
        observations=[
            InquiryObservation(
                concept=concept,
                status="present",
                evidence=evidence,
                source_turn=1,
                confidence=0.9,
            )
        ],
        duration=duration,
        used_medicines=used,
        allergy_or_contraindication=allergy,
        follow_up_question=reply if action == "ask" else "",
        assistant_reply=reply,
        reasoning_summary=f"已确认{evidence}。",
        action_intent=action,
        action_reason="由当前病例信息决定下一步",
        ai_risk_level=risk,
        answered_topics_this_turn=list(semantic_topics),
        topic_evidence=semantic_topics,
        question_topic=infer_question_topic(reply) if action == "ask" else "none",
        clinical_ready=action == "analyze",
        material_symptom_change=material_change,
        symptom_change_type=change_type,
        replaced_concepts=replaced_concepts or [],
        symptom_scope_complete=scope_complete,
        confidence=0.9,
        source=source,
        available=True,
    )


def low_risk_watery_diarrhea_interpretation() -> SymptomInterpretation:
    interpretation = case(
        action="analyze",
        concept="水样腹泻",
        evidence="今天开始拉水样便，目前能喝水",
        duration="今天开始",
        used="未使用",
        allergy="无",
    )
    interpretation.observations = [
        InquiryObservation(
            concept="水样腹泻",
            status="present",
            evidence="今天开始拉水样便",
            source_turn=1,
            confidence=0.95,
        ),
        InquiryObservation(
            concept="饮水情况",
            status="present",
            evidence="目前能喝水",
            source_turn=1,
            confidence=0.95,
        ),
        *[
            InquiryObservation(
                concept=concept,
                status="absent",
                evidence=f"没有{concept}",
                source_turn=1,
                confidence=0.95,
            )
            for concept in (
                "便血",
                "黑便",
                "持续高热",
                "剧烈腹痛",
                "明显脱水",
                "持续呕吐",
            )
        ],
    ]
    return interpretation


GROUNDED_DIARRHEA_TRANSCRIPT = (
    "今天开始拉水样便，目前能喝水，没有便血、没有黑便、没有持续高热、"
    "没有剧烈腹痛、没有明显脱水、没有持续呕吐，没用药也没有过敏"
)


def echo_authorized_diarrhea_combination(_context, _candidates, allowed):
    selected = next(
        item
        for item in allowed
        if item["combination_id"]
        == "candidate-adult-watery-diarrhea-separated-v1"
    )
    return {
        "ok": True,
        "source": "cloud",
        "options": [
            {
                "label": selected["label"],
                "reason": "当前病例符合该分时方案的全部受控条件。",
                "combination_id": selected["combination_id"],
                "authorization_fingerprint": selected[
                    "authorization_fingerprint"
                ],
                "medicine_ids": selected["medicine_ids"],
                "reason_by_medicine": {},
                "usage_by_medicine": {},
            }
        ],
    }


class FakeInterpreter:
    def __init__(self, results: list[SymptomInterpretation], ranking=None) -> None:
        self.results = list(results)
        self.ranking = ranking or {"ok": True, "source": "cloud", "options": []}
        self.contexts: list[dict] = []
        self.profiles: list[dict] = []
        self.opening_profiles: list[dict] = []
        self.rank_candidates_seen: list[dict] = []

    def opening_question(self, profile, fallback):
        self.opening_profiles.append(profile)
        return fallback, "assistant"

    def interpret(self, _transcript, existing, profile):
        self.contexts.append(existing)
        self.profiles.append(profile)
        if not self.results:
            return SymptomInterpretation(
                available=False,
                source="ai_unavailable",
                action_intent="escalate",
                assistant_reply="智能问询暂不可用。",
            )
        return self.results.pop(0)

    def resume_after_vitals(self, existing, profile):
        return self.interpret("体征完成", existing, profile)

    def rank_candidates(self, context, candidates, *, allowed_combinations=None):
        self.rank_candidates_seen.append(
            {
                "context": context,
                "candidates": candidates,
                "allowed_combinations": allowed_combinations or [],
            }
        )
        if callable(self.ranking):
            return self.ranking(
                context,
                candidates,
                allowed_combinations or [],
            )
        return self.ranking


class FakeDispenseService:
    def __init__(self) -> None:
        self.requests = []

    def confirm(self, request):
        self.requests.append(request)
        return DispenseConfirmResponse(
            ok=True,
            dry_run=False,
            message=f"{request.slot}号柜门已打开。",
            record_id=f"record-{len(self.requests)}",
        )


class UnknownResultDispenseService(FakeDispenseService):
    def confirm(self, request):
        self.requests.append(request)
        return DispenseConfirmResponse(
            ok=False,
            dry_run=False,
            message="柜门结果待现场确认，请勿自动重试。",
            record_id="record-unknown-1",
            result_unknown=True,
            retry_safe=False,
        )


class InventoryConfirmationDispenseService(FakeDispenseService):
    def confirm(self, request):
        self.requests.append(request)
        return DispenseConfirmResponse(
            ok=True,
            dry_run=False,
            message=f"{request.slot}号柜门已打开。",
            record_id="record-needs-inventory-confirmation",
            inventory_confirmation_required=True,
        )


class FakeGuestArchiveService:
    def __init__(self) -> None:
        self.requests = []

    def schedule_capture(self, session_id: str, guest_name: str) -> None:
        self.requests.append((session_id, guest_name))


class InquiryOrchestratorTest(unittest.TestCase):
    def test_demo_spo2_cannot_be_attached_as_complete_inquiry_vitals(self) -> None:
        with self.assertRaisesRegex(ValueError, "演示血氧"):
            InquiryVitalsRequest(
                status="complete",
                temperature=36.6,
                heart_rate=72,
                spo2=97,
                spo2_source="demo_fallback",
                spo2_demo_fallback=True,
            )

    def test_failed_demo_spo2_with_measurements_is_rejected_by_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "非完成状态"):
            InquiryVitalsRequest(
                status="failed",
                temperature=36.6,
                heart_rate=72,
                spo2=97,
                temperature_source="gy614_sensor",
                heart_rate_source="uart8_sensor",
                spo2_source="demo_fallback",
                spo2_demo_fallback=True,
            )

    def test_historical_vitals_cannot_be_attached_as_current_complete_measurement(self) -> None:
        with self.assertRaisesRegex(ValueError, "历史体征"):
            InquiryVitalsRequest(
                status="complete",
                temperature=36.6,
                heart_rate=72,
                spo2=97,
                temperature_source="history_fallback",
                heart_rate_source="history_fallback",
                spo2_source="history_fallback",
                historical_fallback=True,
            )

    def test_complete_inquiry_vitals_require_live_metric_provenance(self) -> None:
        with self.assertRaisesRegex(ValueError, "实时来源"):
            InquiryVitalsRequest(
                status="complete",
                temperature=36.6,
                heart_rate=72,
                spo2=97,
            )

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "inquiry.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        # Initialize the fixed-cabinet metadata and its case-scoped combination
        # policies in this temporary database.
        MedicineRepository().list_all()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def service(
        self,
        results: list[SymptomInterpretation],
        *,
        ranking: dict | None = None,
        dispense=None,
    ) -> tuple[InquiryOrchestrator, FakeInterpreter]:
        interpreter = FakeInterpreter(results, ranking)
        return (
            InquiryOrchestrator(
                interpreter=interpreter,
                dispense_service=dispense or FakeDispenseService(),
                guest_archive_service=FakeGuestArchiveService(),
            ),
            interpreter,
        )

    def create(
        self,
        service: InquiryOrchestrator,
        *,
        service_user_id: str = "wang-nainai",
    ):
        return service.create_session(
            InquirySessionCreateRequest(service_user_id=service_user_id)
        )

    def trusted_vitals_request(
        self,
        session,
        *,
        temperature: float = 36.5,
        heart_rate: int = 76,
        spo2: int = 98,
    ) -> InquiryVitalsRequest:
        vitals_session_id = f"trusted-{session.session_id}"
        VitalsRepository().append(
            VitalsRecord(
                id=f"vitals-session-{vitals_session_id}",
                temperature=temperature,
                heart_rate=heart_rate,
                spo2=spo2,
                status="available",
                source="UART8-vitals-24B+GY-614",
                measured_at="2026-08-10 12:00:00",
                source_route="INQUIRY",
                inquiry_session_id=session.session_id,
                attribution_source="INQUIRY_SESSION",
                service_user_id=session.user_id,
                service_user_name_snapshot=session.user_name,
                persona_generation=session.persona_generation,
                temperature_source="gy614_sensor",
                heart_rate_source="uart8_sensor",
                spo2_source="uart8_sensor",
            )
        )
        return InquiryVitalsRequest(
            vitals_session_id=vitals_session_id,
            temperature=temperature,
            heart_rate=heart_rate,
            spo2=spo2,
            temperature_source="gy614_sensor",
            heart_rate_source="uart8_sensor",
            spo2_source="uart8_sensor",
        )

    def test_guest_inquiry_accepts_its_own_completed_live_vitals(self) -> None:
        service, interpreter = self.service(
            [case(action="ask", reply="请描述症状持续了多久。")]
        )
        session = self.create(service, service_user_id="")
        session.stage = "vitals"
        session.next_action = "measure_vitals"
        InquiryRepository().save_session(session)
        request = self.trusted_vitals_request(session)

        updated = service.attach_vitals(session.session_id, request)

        self.assertEqual(updated.vitals["temperature"], 36.5)
        self.assertEqual(updated.vitals["heart_rate"], 76)
        self.assertEqual(updated.vitals["spo2"], 98)
        self.assertEqual(len(interpreter.contexts), 1)
        measurement = VitalsRepository().latest()
        assert measurement is not None
        self.assertEqual(measurement.inquiry_session_id, session.session_id)
        self.assertEqual(measurement.service_user_id, "")
        self.assertEqual(measurement.persona_generation, "")

    def test_orchestrator_rejects_bypassed_failed_demo_without_side_effects(self) -> None:
        service, interpreter = self.service([case(action="analyze")])
        session = self.create(service)
        bypassed = InquiryVitalsRequest.model_construct(
            status="failed",
            temperature=36.6,
            heart_rate=72,
            spo2=97,
            temperature_source="gy614_sensor",
            heart_rate_source="uart8_sensor",
            spo2_source="demo_fallback",
            spo2_demo_fallback=True,
            historical_fallback=False,
            measured_at="2026-08-05T01:20:00+08:00",
            error_message="",
        )

        with self.assertRaisesRegex(ValueError, "本次真实测量"):
            service.attach_vitals(session.session_id, bypassed)

        self.assertIsNone(service.get_session(session.session_id).vitals)
        self.assertEqual(interpreter.contexts, [])
        with db.connect() as conn:
            tool_messages = conn.execute(
                "SELECT COUNT(*) AS count FROM inquiry_messages WHERE session_id=? AND source='vitals_tool'",
                (session.session_id,),
            ).fetchone()["count"]
        self.assertEqual(tool_messages, 0)

    def test_orchestrator_rejects_bypassed_complete_vitals_without_live_provenance(self) -> None:
        service, interpreter = self.service([case(action="analyze")])
        session = self.create(service)
        bypassed = InquiryVitalsRequest.model_construct(
            status="complete",
            temperature=36.6,
            heart_rate=72,
            spo2=97,
            temperature_source=None,
            heart_rate_source=None,
            spo2_source=None,
            spo2_demo_fallback=False,
            historical_fallback=False,
            measured_at="2026-08-05T01:21:00+08:00",
            error_message="",
        )

        with self.assertRaisesRegex(ValueError, "本次真实测量"):
            service.attach_vitals(session.session_id, bypassed)

        self.assertIsNone(service.get_session(session.session_id).vitals)
        self.assertEqual(interpreter.contexts, [])

    def test_orchestrator_rejects_bypassed_historical_reference_without_side_effects(self) -> None:
        service, interpreter = self.service([case(action="analyze")])
        session = self.create(service)
        bypassed = InquiryVitalsRequest.model_construct(
            status="complete",
            temperature=36.4,
            heart_rate=75,
            spo2=98,
            temperature_source="history_fallback",
            heart_rate_source="history_fallback",
            spo2_source="history_fallback",
            spo2_demo_fallback=False,
            historical_fallback=True,
            measured_at="2026-07-20T10:20:00+08:00",
            error_message="",
        )

        with self.assertRaisesRegex(ValueError, "本次真实测量"):
            service.attach_vitals(session.session_id, bypassed)

        self.assertIsNone(service.get_session(session.session_id).vitals)
        self.assertEqual(interpreter.contexts, [])
        with db.connect() as conn:
            tool_messages = conn.execute(
                "SELECT COUNT(*) AS count FROM inquiry_messages WHERE session_id=? AND source='vitals_tool'",
                (session.session_id,),
            ).fetchone()["count"]
        self.assertEqual(tool_messages, 0)

    def test_complete_vitals_from_an_unbound_measurement_session_are_rejected(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="measure_vitals",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="请先测量额温、心率和血氧。",
                    used="未使用",
                    allergy="无",
                ),
                case(
                    action="ask",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="体征已经记录。",
                    used="未使用",
                    allergy="无",
                ),
            ]
        )
        session = self.create(service)
        pending = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我有点头晕，没用药，没有过敏"),
        )
        self.assertEqual(pending.next_action, "measure_vitals")

        with self.assertRaisesRegex(ValueError, "测量会话.*本次问询"):
            service.attach_vitals(
                session.session_id,
                InquiryVitalsRequest(
                    vitals_session_id="vitals-session-from-another-inquiry",
                    temperature=36.5,
                    heart_rate=76,
                    spo2=98,
                    temperature_source="gy614_sensor",
                    heart_rate_source="uart8_sensor",
                    spo2_source="uart8_sensor",
                ),
            )

        self.assertIsNone(service.get_session(session.session_id).vitals)

    def test_registered_identity_is_loaded_once_per_session(self) -> None:
        service, _ = self.service([])
        session = self.create(service)

        self.assertEqual(session.user_name, "王奶奶")
        self.assertEqual(session.stage, "symptoms")
        self.assertEqual(service.get_session(session.session_id).user_id, "wang-nainai")

    def test_archived_identity_cannot_start_a_registered_session(self) -> None:
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status, archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    "legacy-archived-person",
                    "历史归档对象",
                    70,
                    "旧人物资料",
                    "无已知药物过敏",
                    "已归档",
                    "已归档",
                ),
            )
        service, _ = self.service([])

        session = service.create_session(
            InquirySessionCreateRequest(
                service_user_id="legacy-archived-person",
                guest_name="现场访客",
            )
        )

        self.assertEqual(session.user_id, "")
        self.assertEqual(session.user_name, "现场访客")

    def test_registered_long_term_medication_note_is_in_the_model_profile(self) -> None:
        service, interpreter = self.service(
            [case(concept="咽喉疼痛", evidence="嗓子疼", scope_complete=False)]
        )

        session = self.create(service)
        service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我嗓子疼"),
        )

        plan_note = "计划用药按既往有效医嘱执行"
        self.assertIn("高血压", session.user_profile)
        self.assertIn(plan_note, session.user_profile)
        self.assertIn(plan_note, interpreter.opening_profiles[0]["profile"])
        self.assertIn(plan_note, interpreter.profiles[0]["profile"])

    def test_model_controls_the_next_question_without_fixed_field_order(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="ask",
                    concept="体位变化相关不适",
                    evidence="起身时眼前发黑",
                    reply="这种情况是每次起身都会出现，还是偶尔一次？",
                )
            ]
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="起身时眼前会黑一下"),
        )

        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.reply, "这种情况是每次起身都会出现，还是偶尔一次？")
        self.assertEqual(result.extracted_information.observations[0].concept, "体位变化相关不适")

    def test_multiple_literal_complaints_are_preserved_in_the_live_summary(self) -> None:
        service, _ = self.service(
            [
                case(
                    concept="咽喉疼痛",
                    evidence="嗓子疼",
                    duration="今天早上开始",
                    reply="现在有没有发热？",
                )
            ]
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我嗓子疼，同时头有点痛，是今天早上开始的"),
        )

        self.assertIn("咽喉疼痛", result.extracted_information.symptoms_text)
        self.assertIn("头痛", result.extracted_information.symptoms_text)

    def test_four_actual_symptom_followups_are_allowed_before_medicine_check(self) -> None:
        service, _ = self.service(
            [
                case(concept="中暑不适", evidence="高温后头晕", reply="这次不适是在高温日晒后出现的吗？"),
                case(concept="中暑不适", evidence="高温后头晕", reply="现在喝水后能正常留住吗？"),
                case(concept="中暑不适", evidence="高温后头晕", reply="你现在量到的体温是多少度？"),
                case(concept="中暑不适", evidence="高温后头晕", reply="这种不舒服是从什么时候开始的？"),
                case(concept="中暑不适", evidence="高温后头晕", reply="不应出现的第五个症状问题？"),
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )

        first = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="天气很热，我有点中暑头晕"),
        )
        second = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚才在太阳下走了很久"),
        )
        third = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="可以正常喝水"),
        )
        fourth = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="还没量体温"),
        )
        capped = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚才开始的"),
        )

        self.assertIn("什么时候开始", first.reply)
        self.assertIn("喝水", second.reply)
        self.assertIn("体温", third.reply)
        self.assertIn("恶心", fourth.reply)
        self.assertNotIn("第五个", capped.reply)
        self.assertIn("吃过", capped.reply)
        self.assertEqual(len(capped.extracted_information.asked_clarifications), 4)
        self.assertEqual(capped.stage, "clarification")
        self.assertEqual(capped.next_action, "ask")

    def test_offline_rules_do_not_repeat_an_onset_already_given_naturally(self) -> None:
        service, _ = self.service(
            [
                case(source="offline_rules", concept="暑热不适", reply="有没有恶心、乏力或明显出汗？"),
                case(source="offline_rules", concept="暑热不适", reply="之前有没有暴晒或在闷热环境停留？"),
                case(source="offline_rules", concept="暑热不适", reply="休息、通风或补水后有没有缓解？"),
                case(source="offline_rules", concept="暑热不适", reply="我先整理一下：目前主要是暑热不适。这种不舒服持续多久了？"),
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )

        first = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="天气很热，我有点中暑头晕"),
        )
        second = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="有一点恶心，也出了很多汗"),
        )
        third = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚才在太阳下走了很久"),
        )
        summarized = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="喝水休息以后好了一点"),
        )

        self.assertIn("恶心", first.reply)
        self.assertIn("什么时候开始", second.reply)
        self.assertTrue("补水" in third.reply or "喝水" in third.reply)
        self.assertNotIn("持续多久", summarized.reply)
        self.assertIn("体温", summarized.reply)
        self.assertEqual(summarized.stage, "clarification")
        self.assertEqual(summarized.next_action, "ask")

    def test_capped_flow_advances_through_safety_questions_vitals_and_recommendation(self) -> None:
        service, _ = self.service(
            [
                case(reply="这次不适是在高温日晒后出现的吗？"),
                case(reply="现在喝水后能正常留住吗？"),
                case(reply="你现在量到的体温是多少度？"),
                case(reply="这种不舒服是从什么时候开始的？"),
                case(reply="不应出现的第五个症状问题？"),
                case(reply="模型仍想追问", used="未使用"),
                case(reply="模型仍想追问", allergy="无", used="未使用"),
                case(action="analyze", allergy="无", used="未使用", duration="半天"),
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [
                    {
                        "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                        "label": "主方案",
                        "reason": "更贴近当前的暑热不适。",
                    }
                ],
            },
        )
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status, persona_generation
                ) VALUES (
                  'vitals-flow-user', '体征流程测试人物', 66, '', '', '',
                  '已登记', 'vitals-flow-persona-v1'
                )
                """
            )
        session = self.create(service, service_user_id="vitals-flow-user")
        for transcript in ("中暑头晕", "刚才在太阳下走了很久", "可以正常喝水", "还没量体温"):
            result = service.process_turn(
                session.session_id,
                InquiryTurnRequest(transcript=transcript),
            )
        self.assertIn("恶心", result.reply)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚才开始的"),
        )
        self.assertIn("用过药", result.reply)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我刚开始不舒服，哪有那么快吃药"),
        )
        self.assertIn("过敏", result.reply)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="没啥过敏"),
        )
        self.assertEqual(result.next_action, "measure_vitals")

        result = service.attach_vitals(
            session.session_id,
            self.trusted_vitals_request(
                result,
                temperature=36.4,
                heart_rate=78,
                spo2=98,
            ),
        )
        self.assertEqual(result.next_action, "show_recommendation")
        self.assertEqual(result.stage, "result")
        self.assertEqual(result.treatment_options[0].medicines[0].slot, "8")

    def test_capped_flow_advances_when_the_model_is_unavailable(self) -> None:
        unavailable = SymptomInterpretation(
            available=False,
            source="ai_unavailable",
            action_intent="ask",
            assistant_reply="刚才这句话没有整理完整，请换一种说法再说一次。",
        )
        service, _ = self.service(
            [
                case(reply="这次不适是在高温日晒后出现的吗？"),
                case(reply="现在喝水后能正常留住吗？"),
                case(reply="你现在量到的体温是多少度？"),
                case(reply="这种不舒服是从什么时候开始的？"),
                unavailable,
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )

        for transcript in ("中暑头晕", "刚才在太阳下走了很久", "可以正常喝水", "还没量体温"):
            service.process_turn(
                session.session_id,
                InquiryTurnRequest(transcript=transcript),
            )
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚才开始的"),
        )

        self.assertEqual(result.next_action, "ask")
        self.assertIn("用过药", result.reply)
        self.assertNotIn("换一种说法", result.reply)

    def test_contextual_negative_answer_survives_model_failure_after_the_cap(self) -> None:
        unavailable = SymptomInterpretation(
            available=False,
            source="ai_unavailable",
            action_intent="ask",
            assistant_reply="刚才这句话没有整理完整，请换一种说法再说一次。",
        )
        service, _ = self.service(
            [
                case(reply="这次不适是在高温日晒后出现的吗？"),
                case(reply="现在喝水后能正常留住吗？"),
                case(reply="你现在量到的体温是多少度？"),
                case(reply="这种不舒服是从什么时候开始的？"),
                unavailable,
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )

        for transcript in ("中暑头晕", "刚才在太阳下走了很久", "可以正常喝水", "还没量体温"):
            result = service.process_turn(
                session.session_id,
                InquiryTurnRequest(transcript=transcript),
            )
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="刚才开始的"),
        )
        self.assertIn("用过药", result.reply)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="也没有"),
        )

        self.assertEqual(result.extracted_information.used_medicines, "未使用")
        self.assertIn("过敏", result.reply)
        self.assertNotIn("换一种说法", result.reply)

    def test_main_complaint_keeps_all_literal_symptoms_without_accumulating_answers(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="ask",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="这种情况持续多久了？",
                ),
                case(
                    action="ask",
                    concept="头晕",
                    evidence="头晕持续半天",
                    reply="头晕时有没有恶心想吐？",
                    duration="半天",
                ),
            ]
        )
        session = self.create(service)

        first = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="有点头晕，流清鼻涕"),
        )
        second = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="大概半天左右"),
        )

        self.assertEqual(first.extracted_information.symptoms_text, "头晕、流鼻涕")
        self.assertEqual(second.extracted_information.symptoms_text, "头晕、流鼻涕")
        self.assertNotIn("半天", second.extracted_information.symptoms_text)

    def test_reviewed_information_still_honors_the_model_next_action(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="ask",
                    concept="喉咙不适",
                    evidence="喉咙干痒",
                    reply="吞咽时疼痛会明显加重吗？",
                    duration="一天",
                    used="未使用",
                    allergy="头孢过敏",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [{"medicine_ids": ["slot-07-yinhuang"]}],
            },
        )
        session = self.create(service)

        result = service.revise_information(
            session.session_id,
            InquiryInformationRevisionRequest(
                main_complaint="喉咙干痒",
                duration="一天",
                used_medicines="未使用",
                allergy_or_contraindication="头孢过敏",
                finalize=True,
            ),
        )

        self.assertEqual(result.next_action, "ask")
        self.assertEqual(result.reply, "吞咽时疼痛会明显加重吗？")
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(interpreter.rank_candidates_seen, [])

    def test_new_observation_status_replaces_the_previous_status(self) -> None:
        service, _ = self.service(
            [
                SymptomInterpretation(
                    case_summary="用户否认发热。",
                    observations=[
                        InquiryObservation(
                            concept="发热",
                            status="absent",
                            evidence="没有发热",
                            source_turn=2,
                            confidence=0.95,
                        )
                    ],
                    assistant_reply="还有其他不舒服吗？",
                    action_intent="ask",
                    ai_risk_level="low",
                    source="cloud",
                )
            ]
        )
        session = self.create(service)
        session.extracted_information.observations = [
            InquiryObservation(
                concept="发热",
                status="present",
                evidence="刚才感觉发热",
                source_turn=1,
                confidence=0.6,
            )
        ]
        service.repository.save_session(session)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="现在确认没有发热"),
        )

        fever = [value for value in result.extracted_information.observations if value.concept == "发热"]
        self.assertEqual(len(fever), 1)
        self.assertEqual(fever[0].status, "absent")

    def test_vitals_resume_the_same_ai_session(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="measure_vitals",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="请先测量额温、心率和血氧。",
                    used="未使用",
                    allergy="无",
                ),
                case(
                    action="ask",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="体征已经记录。头晕是在起身时更明显吗？",
                    used="未使用",
                    allergy="无",
                ),
            ]
        )
        session = self.create(service)
        pending = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我有点头晕，没用药，没有过敏"),
        )
        self.assertEqual(pending.next_action, "measure_vitals")
        self.assertIn("额头", pending.reply)
        self.assertIn("手指", pending.reply)
        self.assertIn("开始测量", pending.reply)

        resumed = service.attach_vitals(
            session.session_id,
            self.trusted_vitals_request(
                pending,
                temperature=36.5,
                heart_rate=76,
                spo2=98,
            ),
        )

        self.assertEqual(resumed.next_action, "ask")
        self.assertEqual(resumed.vitals["spo2"], 98)
        self.assertEqual(resumed.vitals["status"], "complete")
        self.assertEqual(interpreter.contexts[-1]["vitals"]["heart_rate"], 76)
        self.assertEqual(resumed.messages[-2].source, "vitals_tool")

    def test_local_like_analysis_cannot_skip_vitals_for_heat_and_dizziness(self) -> None:
        local_interpretation = case(
            action="analyze",
            concept="中暑和头晕",
            evidence="中暑后有点头晕",
            reply="我来结合现有信息分析。",
            duration="半天",
            used="未使用",
            allergy="无",
        )
        local_interpretation.source = "local_llm"
        service, _ = self.service(
            [local_interpretation]
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我有点中暑头晕，半天了，没用药，也没有过敏"),
        )

        self.assertEqual(result.next_action, "measure_vitals")
        self.assertEqual(result.stage, "vitals")
        self.assertIn("额头", result.reply)

    def test_forced_vitals_guidance_does_not_mix_in_an_unanswered_question(self) -> None:
        local_interpretation = case(
            action="ask",
            concept="头晕",
            evidence="有点头晕",
            reply="这次不舒服以后有没有用过药？",
            duration="半天",
        )
        local_interpretation.source = "local_llm"
        service, _ = self.service([local_interpretation])
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我有点头晕，已经半天了"),
        )

        self.assertEqual(result.next_action, "measure_vitals")
        self.assertNotIn("用过药", result.reply)
        self.assertIn("开始测量", result.reply)

    def test_cancelled_vitals_return_to_the_same_ai_session(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="measure_vitals",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="头晕可能需要结合体征确认。",
                    used="未使用",
                    allergy="无",
                ),
                case(
                    action="ask",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="没关系，我们继续。头晕是在起身时更明显吗？",
                    used="未使用",
                    allergy="无",
                ),
            ]
        )
        session = self.create(service)
        service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我有点头晕，没用药，没有过敏"),
        )

        resumed = service.attach_vitals(
            session.session_id,
            InquiryVitalsRequest(status="cancelled"),
        )

        self.assertEqual(resumed.next_action, "ask")
        self.assertEqual(resumed.vitals["status"], "cancelled")
        self.assertEqual(interpreter.contexts[-1]["vitals_event"], "用户取消了本次体征测量，请结合已有信息自然继续问询。")
        self.assertTrue(any(message.source == "vitals_tool" for message in resumed.messages))

    def test_model_cannot_measure_before_a_complaint_is_understood(self) -> None:
        interpretation = SymptomInterpretation(
            assistant_reply="先测一下体征。",
            action_intent="measure_vitals",
            action_reason="尚未形成主诉",
            source="cloud",
            available=True,
        )
        service, _ = self.service([interpretation])
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我不知道怎么说"),
        )

        self.assertEqual(result.next_action, "ask")
        self.assertEqual(result.reply, "现在最不舒服的具体是什么？")

    def test_ai_unavailable_keeps_the_session_retryable_without_generating_candidates(self) -> None:
        unavailable = SymptomInterpretation(
            available=False,
            source="ai_unavailable",
            action_intent="escalate",
            assistant_reply="智能问询当前暂不可用，本次不会生成取药候选。",
        )
        service, _ = self.service([unavailable])
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我中暑头晕"),
        )

        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertIn("什么时候", result.reply)
        self.assertNotIn("暂不可用", result.reply)
        self.assertNotIn("规则", result.reply)
        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.treatment_options, [])

    def test_model_escalation_never_enters_candidate_ranking(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="escalate",
                    reply="这次情况需要医生进一步确认，我先不展示家庭药品。",
                    used="未使用",
                    allergy="无",
                    risk="medium",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [{"medicine_ids": ["slot-08-huoxiang-zhengqi"]}],
            },
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="这个情况我说不清楚"),
        )

        self.assertEqual(result.next_action, "escalate")
        self.assertEqual(result.reply, "这次情况需要医生进一步确认，我先不展示家庭药品。")
        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(interpreter.rank_candidates_seen, [])

    def test_candidate_ranking_failure_keeps_the_session_retryable(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="analyze",
                    concept="便秘",
                    evidence="排便困难",
                    duration="两天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={
                "ok": False,
                "source": "ai_unavailable",
                "message": "",
            },
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="排便困难两天，没用药，没有过敏"),
        )

        self.assertEqual(result.session_id, session.session_id)
        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertIn("稍后重新匹配", result.reply)
        self.assertNotIn("连接", result.reply)
        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(result.extracted_information.duration, "两天")
        self.assertEqual(result.extracted_information.used_medicines, "未使用")
        self.assertEqual(result.extracted_information.allergy_or_contraindication, "无")

        interpreter.results.append(
            case(
                action="analyze",
                concept="便秘",
                evidence="排便困难",
                duration="两天",
                used="未使用",
                allergy="无",
            )
        )
        interpreter.ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "label": "主方案",
                    "medicine_ids": ["slot-06-lactulose"],
                }
            ],
        }
        retried = service.process_turn(
            result.session_id,
            InquiryTurnRequest(transcript="请重新匹配"),
        )

        self.assertEqual(retried.session_id, session.session_id)
        self.assertEqual(retried.stage, "result")
        self.assertEqual(retried.next_action, "show_recommendation")
        self.assertTrue(retried.can_view_medicines)

    def test_model_end_closes_the_session_without_a_candidate(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="end",
                    reply="好的，本次问询先到这里。",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [{"medicine_ids": ["slot-08-huoxiang-zhengqi"]}],
            },
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我先不继续了"),
        )

        self.assertEqual(result.next_action, "complete")
        self.assertEqual(result.reply, "好的，本次问询先到这里。")
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(interpreter.rank_candidates_seen, [])

    def test_model_end_still_ranks_care_supplies_when_user_did_not_end_the_session(self) -> None:
        interpretation = case(
            action="end",
            concept="手部浅表刀伤",
            evidence="手部刀伤不深，出血已经止住，需要纱布覆盖",
            reply="伤口目前风险较低，注意清洁和覆盖。",
            duration="刚发生",
            used="未使用",
            allergy="无",
        )
        interpretation.observations = [
            InquiryObservation(
                concept="浅表伤口",
                status="present",
                evidence="手部刀伤不深",
                source_turn=1,
                confidence=0.95,
            ),
            InquiryObservation(
                concept="止血情况",
                status="present",
                evidence="出血已经止住",
                source_turn=1,
                confidence=0.95,
            ),
            InquiryObservation(
                concept="覆盖方式",
                status="present",
                evidence="需要纱布覆盖",
                source_turn=1,
                confidence=0.95,
            ),
            *[
                InquiryObservation(
                    concept=concept,
                    status="absent",
                    evidence=f"没有{concept}",
                    source_turn=1,
                    confidence=0.95,
                )
                for concept in (
                    "深部伤口",
                    "动物咬伤",
                    "持续出血",
                    "伤口感染",
                    "异物残留",
                )
            ],
        ]

        def select_gauze_combination(_context, _candidates, allowed):
            selected = next(
                item
                for item in allowed
                if item["combination_id"]
                == "candidate-superficial-wound-gauze-v1"
            )
            return {
                "ok": True,
                "source": "cloud",
                "options": [
                    {
                        "label": selected["label"],
                        "reason": "伤口较浅且已经止血，可先完成清洁消毒和覆盖保护。",
                        "combination_id": selected["combination_id"],
                        "authorization_fingerprint": selected[
                            "authorization_fingerprint"
                        ],
                        "medicine_ids": selected["medicine_ids"],
                    }
                ],
            }

        service, interpreter = self.service(
            [interpretation],
            ranking=select_gauze_combination,
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript=(
                    "手部刀伤不深，出血已经止住，需要纱布覆盖，没有深部伤口、"
                    "没有动物咬伤、没有持续出血、没有伤口感染、没有异物残留，"
                    "没有用药也没有过敏"
                )
            ),
        )

        self.assertEqual(result.next_action, "show_recommendation")
        self.assertTrue(result.can_view_medicines)
        self.assertEqual(
            [medicine.id for medicine in result.treatment_options[0].medicines],
            ["slot-17-iodophor", "slot-22-cotton-swab", "slot-10-gauze"],
        )
        self.assertTrue(interpreter.rank_candidates_seen)

    def test_real_multi_medicine_plan_is_selected_only_from_the_case_authorization(
        self,
    ) -> None:
        dispense = FakeDispenseService()
        service, interpreter = self.service(
            [low_risk_watery_diarrhea_interpretation()],
            ranking=echo_authorized_diarrhea_combination,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="wang-nainai")
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript=GROUNDED_DIARRHEA_TRANSCRIPT,
            ),
        )

        self.assertTrue(result.can_view_medicines)
        self.assertEqual(len(result.treatment_options), 1)
        option = result.treatment_options[0]
        self.assertEqual(
            option.combination_id,
            "candidate-adult-watery-diarrhea-separated-v1",
        )
        self.assertEqual(
            [medicine.id for medicine in option.medicines],
            ["slot-03-diosmectite", "slot-09-bifid-triple"],
        )
        self.assertIn("间隔至少 2 小时", option.medicines[1].recommended_usage)
        self.assertTrue(interpreter.rank_candidates_seen[0]["allowed_combinations"])

        confirmed = service.confirm_treatment(
            session.session_id,
            InquiryTreatmentConfirmRequest(
                option_id=option.option_id,
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )
        self.assertTrue(confirmed.ok)
        self.assertEqual(len(dispense.requests), 1)
        self.assertEqual(
            dispense.requests[0].medicine_id,
            "slot-03-diosmectite",
        )

        with db.connect() as conn:
            conn.execute(
                """
                UPDATE approved_medicine_combinations
                SET review_status='invalidated', updated_at=?
                WHERE combination_id=?
                """,
                (
                    db.now_text(),
                    "candidate-adult-watery-diarrhea-separated-v1",
                ),
            )
        with self.assertRaises(DispenseError) as revoked:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=1,
                ),
            )
        self.assertEqual(revoked.exception.status_code, 409)
        self.assertEqual(len(dispense.requests), 1)

    def test_inquiry_transport_unknown_is_preserved_with_stable_action_identity(self) -> None:
        dispense = UnknownResultDispenseService()
        service, _interpreter = self.service(
            [low_risk_watery_diarrhea_interpretation()],
            ranking=echo_authorized_diarrhea_combination,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="wang-nainai")
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript=GROUNDED_DIARRHEA_TRANSCRIPT),
        )
        option = result.treatment_options[0]

        confirmed = service.confirm_treatment(
            session.session_id,
            InquiryTreatmentConfirmRequest(
                option_id=option.option_id,
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )

        self.assertFalse(confirmed.ok)
        self.assertEqual(confirmed.status, "failed")
        self.assertTrue(confirmed.result_unknown)
        self.assertFalse(confirmed.retry_safe)
        self.assertTrue(confirmed.items[0].result_unknown)
        self.assertFalse(confirmed.items[0].retry_safe)
        self.assertIn("现场确认", confirmed.items[0].message)
        self.assertIn("请勿自动重试", confirmed.message)
        self.assertEqual(
            dispense.requests[0].request_id,
            f"{session.session_id}:{option.option_id}:0",
        )

    def test_fabricated_red_flag_absences_do_not_authorize_a_real_combination(
        self,
    ) -> None:
        service, interpreter = self.service(
            [low_risk_watery_diarrhea_interpretation()],
            ranking={"ok": True, "source": "cloud", "options": []},
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="今天开始拉水样便，目前能喝水，没用药也没有过敏",
            ),
        )

        self.assertFalse(result.can_view_medicines)
        self.assertEqual(
            interpreter.rank_candidates_seen[0]["allowed_combinations"],
            [],
        )

    def test_low_risk_with_safe_matches_gets_two_observation_options_when_model_returns_none(
        self,
    ) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "assessment": {
                "summary": "目前表现较轻，可以先观察变化。",
                "possible_conditions": [],
                "next_steps": ["先休息并观察症状变化"],
                "seek_care_if": ["持续发热或明显加重"],
            },
            "options": [],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="轻微感冒发热头痛",
                    evidence="有一点发热和头痛",
                    duration="刚开始",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="")

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="刚开始有一点发热和头痛，没有用药也没有过敏"
            ),
        )

        self.assertEqual(result.risk_level, "low")
        self.assertEqual(result.stage, "result")
        self.assertEqual(result.next_action, "show_recommendation")
        self.assertTrue(result.can_view_medicines)
        self.assertEqual(len(result.treatment_options), 2)
        option_ids = {
            medicine.id
            for option in result.treatment_options
            for medicine in option.medicines
        }
        self.assertEqual(
            option_ids,
            {"slot-01-fufang-ganmaoling", "slot-13-ibuprofen"},
        )
        for option in result.treatment_options:
            self.assertIn("观察", option.label)
            self.assertIn("先观察", option.when)
        self.assertIn("先观察", result.reply)

        selected = result.treatment_options[1]
        confirmed = service.confirm_treatment(
            session.session_id,
            InquiryTreatmentConfirmRequest(
                option_id=selected.option_id,
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )

        self.assertTrue(confirmed.ok)
        self.assertEqual(
            dispense.requests[0].medicine_id,
            selected.medicines[0].id,
        )

    def test_single_model_choice_gets_a_distinct_observation_alternative(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "assessment": {
                "summary": "轻微发热和头痛可以先观察。",
                "possible_conditions": [],
                "next_steps": ["休息并补充水分"],
                "seek_care_if": ["体温升高或疼痛加重"],
            },
            "options": [
                {
                    "medicine_ids": ["slot-01-fufang-ganmaoling"],
                    "label": "主方案",
                    "reason": "更贴近轻微感冒表现。",
                }
            ],
        }
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="轻微感冒发热头痛",
                    evidence="有一点发热和头痛",
                    duration="刚开始",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
        )
        session = self.create(service, service_user_id="")

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="刚开始有一点发热和头痛，没有用药也没有过敏"
            ),
        )

        self.assertEqual(len(result.treatment_options), 2)
        self.assertEqual(
            [option.medicines[0].id for option in result.treatment_options],
            ["slot-01-fufang-ganmaoling", "slot-13-ibuprofen"],
        )
        self.assertEqual(result.treatment_options[1].option_id, "B")
        self.assertIn("主方案", result.treatment_options[1].label)
        self.assertIn("观察后备选", result.treatment_options[1].label)
        self.assertIn("观察后备选", result.reply)

    def test_observation_fallback_does_not_override_when_every_condition_needs_exclusion(
        self,
    ) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "assessment": {
                "summary": "仍需排除需要专业处理的情况。",
                "possible_conditions": [
                    {
                        "name": "需要进一步排查的感染",
                        "likelihood": "needs_exclusion",
                        "supporting_evidence_ids": [],
                        "non_supporting_evidence_ids": [],
                    }
                ],
                "next_steps": ["继续观察并联系专业人员"],
                "seek_care_if": ["发热或疼痛加重"],
            },
            "options": [],
        }
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="轻微感冒发热头痛",
                    evidence="有一点发热和头痛",
                    duration="刚开始",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
        )
        session = self.create(service, service_user_id="")

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="刚开始有一点发热和头痛，没有用药也没有过敏"
            ),
        )

        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(result.next_action, "complete")

    def test_observation_fallback_uses_only_safety_cleaned_possible_conditions(
        self,
    ) -> None:
        ranking = {
            "ok": True,
            "source": "cloud_responses",
            "assessment": {
                "summary": "模型同时给出了取药指令和需要进一步排查的情况。",
                "possible_conditions": [
                    {
                        "name": "建议直接取药的情况",
                        "likelihood": "possible",
                        "supporting_evidence_ids": [],
                        "non_supporting_evidence_ids": [],
                    },
                    {
                        "name": "需要进一步排查的感染",
                        "likelihood": "needs_exclusion",
                        "supporting_evidence_ids": [],
                        "non_supporting_evidence_ids": [],
                    },
                ],
                "next_steps": ["继续观察并联系专业人员"],
                "seek_care_if": ["发热或疼痛加重"],
            },
            "options": [],
        }
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="轻微感冒发热头痛",
                    evidence="有一点发热和头痛",
                    duration="刚开始",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
        )
        session = self.create(service, service_user_id="")

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="刚开始有一点发热和头痛，没有用药也没有过敏"
            ),
        )

        self.assertEqual(
            [
                condition.name
                for condition in (
                    result.extracted_information.final_assessment.possible_conditions
                )
            ],
            ["需要进一步排查的感染"],
        )
        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(result.next_action, "complete")

    def test_low_risk_cough_keeps_a_safe_observation_option_when_one_cause_needs_exclusion(
        self,
    ) -> None:
        ranking = {
            "ok": True,
            "source": "cloud_responses",
            "assessment": {
                "summary": (
                    "咳嗽和发冷可能与上呼吸道不适有关；"
                    "头晕仍需观察或排除低血糖反应。"
                ),
                "possible_conditions": [
                    {
                        "name": "上呼吸道感染",
                        "likelihood": "possible",
                        "supporting_evidence_ids": [],
                        "non_supporting_evidence_ids": [],
                    },
                    {
                        "name": "低血糖反应",
                        "likelihood": "needs_exclusion",
                        "supporting_evidence_ids": [],
                        "non_supporting_evidence_ids": [],
                    },
                ],
                "next_steps": ["监测血糖并观察咳嗽变化"],
                "seek_care_if": ["咳嗽加剧或头晕加重"],
            },
            "options": [],
        }
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="咳嗽头晕发冷",
                    evidence="今天晚上有一点咳嗽、头晕和发冷",
                    duration="今天晚上",
                    used="未使用",
                    allergy="无已知药物过敏",
                )
            ],
            ranking=ranking,
        )

        result = service.process_turn(
            self.create(service, service_user_id="li-yeye").session_id,
            InquiryTurnRequest(
                transcript=(
                    "今天晚上有一点咳嗽、头晕和发冷，"
                    "没有呼吸困难，没有用药，也没有药物过敏"
                )
            ),
        )

        option_ids = {
            medicine.id
            for option in result.treatment_options
            for medicine in option.medicines
        }
        self.assertTrue(result.can_view_medicines)
        self.assertEqual(len(result.treatment_options), 2)
        self.assertIn("slot-01-fufang-ganmaoling", option_ids)
        self.assertIn("slot-07-yinhuang", option_ids)
        self.assertNotIn("slot-05-nin-jiom-pei-pa-koa", option_ids)
        notice_text = " ".join(
            notice.message for notice in result.medication_safety_notices
        )
        self.assertIn("蜜炼川贝枇杷膏", notice_text)
        self.assertNotIn("银黄颗粒", notice_text)

    def test_observation_fallback_never_auto_selects_a_prescription_plan_item(
        self,
    ) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "assessment": {
                "summary": "鼻部表现较轻，可以先观察。",
                "possible_conditions": [],
                "next_steps": ["先观察鼻部症状"],
                "seek_care_if": ["症状持续加重"],
            },
            "options": [],
        }
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="轻微过敏性鼻炎",
                    evidence="打喷嚏并流清水样鼻涕",
                    duration="刚开始",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
        )
        session = self.create(service, service_user_id="li-yeye")

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="刚开始打喷嚏并流清水样鼻涕，没有用药也没有过敏"
            ),
        )

        fallback_ids = {
            medicine.id
            for option in result.treatment_options
            for medicine in option.medicines
        }
        self.assertEqual(fallback_ids, {"slot-18-budesonide-nasal"})
        self.assertNotIn("slot-23-desloratadine", fallback_ids)

    def test_low_risk_without_a_matching_candidate_returns_neutral_care_advice(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="轻微困倦",
                    evidence="只是有一点困",
                    duration="刚发生",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={"ok": True, "source": "cloud", "options": []},
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="只是有一点困，没有其他不适，没有用药也没有过敏"),
        )

        self.assertEqual(result.risk_level, "low")
        self.assertEqual(result.stage, "result")
        self.assertEqual(result.next_action, "complete")
        self.assertIn("没有检测到合适药物", result.reply)
        self.assertNotIn("不要自行新增用药", result.reply)
        self.assertFalse(result.can_view_medicines)

    def test_hard_emergency_signal_overrides_model_and_skips_it(self) -> None:
        service, interpreter = self.service([case(action="analyze", used="未使用", allergy="无")])
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我胸痛并且呼吸困难"),
        )

        self.assertEqual(result.risk_level, "emergency")
        self.assertEqual(result.next_action, "escalate")
        self.assertEqual(interpreter.contexts, [])

    def test_ai_can_only_choose_from_the_hard_safe_pool(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "option_id": "primary",
                    "label": "主方案",
                    "reason": "更贴近暑热后伴随的胃肠不适。",
                    "medicine_ids": ["slot-08-huoxiang-zhengqi", "slot-04-amoxicillin"],
                },
                {
                    "option_id": "alternative",
                    "label": "备选方案",
                    "reason": "如果主要是反酸，可对照这一选择。",
                    "medicine_ids": ["slot-12-hydrotalcite"],
                },
            ],
        }
        service, interpreter = self.service(
            [
                case(
                    action="analyze",
                    concept="暑热后胃肠不适",
                    evidence="晒后头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="青霉素过敏",
                    risk="medium",
                )
            ],
            ranking=ranking,
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="晒后头晕恶心半天，没用药，青霉素过敏"),
        )

        self.assertEqual(result.risk_level, "medium")
        self.assertTrue(result.can_view_medicines)
        self.assertLessEqual(len(result.treatment_options), 2)
        ids = {medicine.id for option in result.treatment_options for medicine in option.medicines}
        self.assertNotIn("slot-04-amoxicillin", ids)
        self.assertTrue(interpreter.rank_candidates_seen)

    def test_ai_cannot_choose_a_safe_medicine_that_was_not_in_its_focused_pool(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="analyze",
                    concept="暑热后胃肠不适",
                    evidence="晒后头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                    risk="medium",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [
                    {
                        "label": "模型越界方案",
                        "reason": "模型返回了没有看见的候选药品。",
                        "medicine_ids": ["slot-12-hydrotalcite"],
                    }
                ],
            },
        )
        knowledge = service.safety_engine.knowledge

        def without_hydrotalcite(_text, candidates, *, limit=8):
            return [
                candidate
                for candidate in candidates
                if candidate.id != "slot-12-hydrotalcite"
            ][:min(limit, 1)]

        with patch.object(knowledge, "focus_candidate_pool", side_effect=without_hydrotalcite):
            result = service.process_turn(
                self.create(service).session_id,
                InquiryTurnRequest(transcript="晒后头晕恶心半天，没用药也没有过敏"),
            )

        self.assertTrue(interpreter.rank_candidates_seen)
        shown_ids = {
            medicine.id
            for option in result.treatment_options
            for medicine in option.medicines
        }
        self.assertNotIn("slot-12-hydrotalcite", shown_ids)
        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertIn("药品匹配服务", result.reply)

    def test_candidate_retrieval_keeps_grounded_user_symptoms_dropped_by_extraction(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="analyze",
                    concept="腹痛",
                    evidence="肚子有点痛",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={"ok": True, "source": "cloud", "options": []},
        )

        service.process_turn(
            self.create(service).session_id,
            InquiryTurnRequest(
                transcript="肚子有点痛，还有一点窜稀，半天了，没有用药也没有过敏"
            ),
        )

        seen_ids = {
            candidate["id"]
            for candidate in interpreter.rank_candidates_seen[0]["candidates"]
        }
        self.assertIn("slot-03-diosmectite", seen_ids)
        self.assertIn("slot-09-bifid-triple", seen_ids)

    def test_used_ingredient_conflict_is_visible_while_another_safe_option_remains(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="咽喉疼痛",
                    evidence="咽喉疼痛且有轻微发热",
                    duration="半天",
                    used="对乙酰氨基酚",
                    allergy="无",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [
                    {
                        "label": "咽喉护理方案",
                        "reason": "针对当前咽喉疼痛进行核对。",
                        "medicine_ids": ["slot-07-yinhuang"],
                    }
                ],
            },
        )

        result = service.process_turn(
            self.create(service, service_user_id="wang-nainai").session_id,
            InquiryTurnRequest(
                transcript="咽喉疼痛且有轻微发热半天，已经用了对乙酰氨基酚，没有过敏"
            ),
        )

        self.assertTrue(result.can_view_medicines)
        self.assertEqual(result.treatment_options[0].medicines[0].id, "slot-07-yinhuang")
        notice_codes = [
            notice.code for notice in result.medication_safety_notices
        ]
        self.assertEqual(notice_codes.count("used_medicine_duplicate"), 2)
        self.assertIn("history_contraindication", notice_codes)
        notice_text = " ".join(
            notice.message for notice in result.medication_safety_notices
        )
        self.assertIn("复方感冒灵颗粒", notice_text)
        self.assertIn("布洛芬缓释胶囊", notice_text)
        self.assertIn("重复", notice_text)

    def test_all_relevant_candidates_blocked_by_safety_returns_notices_not_ranking_failure(self) -> None:
        medicine_repository = MedicineRepository()
        for medicine in medicine_repository.list_all():
            medicine_repository.update(
                medicine.id,
                {"stock": 1 if medicine.id == "slot-13-ibuprofen" else 0},
            )
        service, interpreter = self.service(
            [
                case(
                    action="analyze",
                    concept="头痛",
                    evidence="逐渐出现的轻微头痛，没有神经危险表现",
                    duration="半天",
                    used="芬必得",
                    allergy="无",
                )
            ],
            ranking={"ok": False, "source": "cloud", "message": "排序服务暂时不可用"},
        )

        result = service.process_turn(
            self.create(service, service_user_id="li-yeye").session_id,
            InquiryTurnRequest(
                transcript="逐渐出现的轻微头痛半天，已经用了芬必得，没有过敏"
            ),
        )

        self.assertEqual(result.next_action, "complete")
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(
            [notice.code for notice in result.medication_safety_notices],
            ["used_medicine_duplicate"],
        )
        self.assertNotIn("匹配服务", result.reply)
        self.assertIn("安全提醒", result.reply)
        self.assertEqual(
            interpreter.rank_candidates_seen,
            [],
            "an empty deterministic safe pool must not wait for cloud ranking",
        )

    def test_deterministic_safety_notice_is_identical_across_interpreter_sources(self) -> None:
        notices_by_source: dict[str, list[tuple[str, str]]] = {}
        for source in ("cloud", "local_llm", "offline_rules"):
            with self.subTest(source=source):
                service, _ = self.service(
                    [
                        case(
                            action="analyze",
                            concept="便秘",
                            evidence="排便困难但没有腹痛",
                            duration="两天",
                            used="乳果糖",
                            allergy="无",
                            source=source,
                        )
                    ],
                    ranking={"ok": True, "source": source, "options": []},
                )

                result = service.process_turn(
                    self.create(service).session_id,
                    InquiryTurnRequest(
                        transcript="排便困难两天但没有腹痛，已经用了乳果糖，没有过敏"
                    ),
                )

                notices_by_source[source] = [
                    (notice.code, notice.message)
                    for notice in result.medication_safety_notices
                ]

        self.assertTrue(notices_by_source["cloud"])
        self.assertEqual(notices_by_source["local_llm"], notices_by_source["cloud"])
        self.assertEqual(notices_by_source["offline_rules"], notices_by_source["cloud"])

    def test_candidate_is_revalidated_after_model_ranking_before_it_is_displayed(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="反酸烧心",
                    evidence="饭后反酸烧心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [
                    {
                        "label": "胃部护理",
                        "reason": "与当前反酸表现相关。",
                        "medicine_ids": ["slot-12-hydrotalcite"],
                    }
                ],
            },
        )
        original_repository = service.safety_engine.knowledge.medicine_repository
        available = original_repository.get_by_id("slot-12-hydrotalcite")
        self.assertIsNotNone(available)

        class InventoryChangedDuringRanking:
            def __init__(self):
                self.calls = 0

            def list_all(inner_self):
                inner_self.calls += 1
                stock = 1 if inner_self.calls == 1 else 0
                return [available.model_copy(update={"stock": stock})]

        live_repository = InventoryChangedDuringRanking()
        service.safety_engine.knowledge.medicine_repository = live_repository

        result = service.process_turn(
            self.create(service).session_id,
            InquiryTurnRequest(transcript="饭后反酸烧心半天，没有用药和过敏"),
        )

        self.assertGreaterEqual(live_repository.calls, 2)
        self.assertEqual(result.treatment_options, [])
        self.assertFalse(result.can_view_medicines)

    def test_unknown_allergy_or_current_medicine_blocks_cabinet_candidate(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="analyze",
                    duration="一天",
                    used="不确定",
                    allergy="不确定",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [
                    {
                        "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                        "reason": "更贴近当前情况。",
                    }
                ],
            },
        )
        session = self.create(service)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="不舒服一天，用药和过敏都不确定"),
        )

        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertIn("用过药", result.reply)
        self.assertEqual(result.treatment_options, [])
        self.assertEqual(interpreter.rank_candidates_seen, [])

    def test_missing_allergy_information_is_asked_before_candidate_ranking(self) -> None:
        service, interpreter = self.service(
            [
                case(
                    action="analyze",
                    duration="一天",
                    used="未使用",
                    allergy="",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [{"medicine_ids": ["slot-08-huoxiang-zhengqi"]}],
            },
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="不舒服一天，这次还没有用药"),
        )

        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertIn("过敏", result.reply)
        self.assertFalse(result.can_view_medicines)
        self.assertEqual(interpreter.rank_candidates_seen, [])

    def test_bare_medicine_answer_is_bound_to_the_pending_question(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="便秘",
                    evidence="排便困难",
                    duration="两天",
                    used="",
                    allergy="无",
                ),
                case(
                    action="analyze",
                    concept="便秘",
                    evidence="排便困难",
                    duration="两天",
                    used="",
                    allergy="无",
                ),
            ]
        )
        session = self.create(service)
        medicine_question = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="排便困难两天，没有药物过敏"),
        )
        self.assertEqual(
            medicine_question.extracted_information.pending_clarification,
            "used_medicines",
        )

        continued = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="没吃"),
        )

        self.assertEqual(continued.extracted_information.used_medicines, "未使用")
        self.assertNotEqual(
            continued.extracted_information.pending_clarification,
            "used_medicines",
        )
        self.assertNotIn("有没有吃过", continued.reply)

    def test_bare_medicine_name_answers_the_previous_allergy_question(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="头痛",
                    evidence="今天早上开始头痛",
                    duration="今天早上开始",
                    used="未使用",
                    allergy="",
                ),
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )
        session.extracted_information = InquiryExtractedInformation(
            case_summary="今天早上开始头痛。",
            symptoms_text="头痛",
            duration="今天早上开始",
            used_medicines="未使用",
            allergy_or_contraindication="",
            symptom_scope_confirmed=True,
            symptom_collection_complete=True,
            pending_clarification="allergy_or_contraindication",
        )
        session.stage = "clarification"
        session.next_action = "ask"
        session.reply = "接下来确认用药安全：你有没有药物过敏，或明确不能使用的药物？"
        first = service._commit(session)

        second = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="银黄颗粒"),
        )

        self.assertEqual(
            second.extracted_information.allergy_or_contraindication,
            "银黄颗粒过敏",
        )
        self.assertNotIn("有没有药物过敏", second.reply)
        self.assertNotEqual(second.reply, first.reply)

    def test_short_no_after_allergy_question_advances_without_repeating_it(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="头痛",
                    evidence="今天早上开始头痛",
                    duration="今天早上开始",
                    used="未使用",
                    allergy="不确定",
                ),
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )
        session.extracted_information = InquiryExtractedInformation(
            case_summary="今天早上开始头痛。",
            symptoms_text="头痛",
            duration="今天早上开始",
            used_medicines="未使用",
            allergy_or_contraindication="",
            symptom_scope_confirmed=True,
            symptom_collection_complete=True,
            pending_clarification="allergy_or_contraindication",
        )
        session.stage = "clarification"
        session.next_action = "ask"
        session.reply = "接下来确认用药安全：你有没有药物过敏，或明确不能使用的药物？"
        first = service._commit(session)

        second = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="无"),
        )

        self.assertEqual(second.extracted_information.allergy_or_contraindication, "无")
        self.assertNotIn("有没有药物过敏", second.reply)
        self.assertNotEqual(second.reply, first.reply)

    def test_negated_massive_bleeding_is_not_treated_as_an_emergency(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="ask",
                    concept="腿部擦伤",
                    evidence="腿部轻微擦伤，没有什么大出血",
                    reply="擦伤处有没有异物或明显肿胀？",
                )
            ]
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="腿部有点擦伤，没有什么大出血"),
        )

        self.assertNotEqual(result.risk_level, "emergency")
        self.assertEqual(result.next_action, "ask")

    def test_displayed_option_is_revalidated_before_opening(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    "label": "主方案",
                    "reason": "更贴近当前的暑湿不适。",
                }
            ],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="暑湿不适",
                    evidence="头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="头晕恶心半天，没用药，没有过敏"),
        )
        option = result.treatment_options[0]

        response = service.confirm_treatment(
            session.session_id,
            InquiryTreatmentConfirmRequest(
                option_id=option.option_id,
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.status, "complete")
        self.assertEqual(dispense.requests[0].medicine_id, "slot-08-huoxiang-zhengqi")

    def test_real_inquiry_dispense_exposes_required_inventory_confirmation(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    "label": "主方案",
                    "reason": "更贴近当前的暑湿不适。",
                }
            ],
        }
        dispense = InventoryConfirmationDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="暑湿不适",
                    evidence="头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="头晕恶心半天，没用药，没有过敏"),
        )

        response = service.confirm_treatment(
            session.session_id,
            InquiryTreatmentConfirmRequest(
                option_id=result.treatment_options[0].option_id,
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )

        self.assertTrue(response.items[0].inventory_confirmation_required)
        self.assertEqual(
            response.items[0].record_id,
            "record-needs-inventory-confirmation",
        )

    def test_inventory_change_after_display_fails_closed_before_hardware(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    "label": "主方案",
                    "reason": "更贴近当前的暑湿不适。",
                }
            ],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="暑湿不适",
                    evidence="头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="头晕恶心半天，没用药，没有过敏"),
        )
        option = result.treatment_options[0]
        MedicineRepository().update("slot-08-huoxiang-zhengqi", {"stock": 0})

        with self.assertRaises(DispenseError) as raised:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=0,
                ),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(dispense.requests, [])
        invalidated = service.get_session(session.session_id)
        self.assertFalse(invalidated.can_view_medicines)
        self.assertEqual(invalidated.treatment_options, [])
        self.assertEqual(
            [notice.code for notice in invalidated.medication_safety_notices],
            ["inventory_changed"],
        )

    def test_medicine_identity_change_after_display_fails_closed_before_hardware(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    "label": "主方案",
                    "reason": "更贴近当前的暑湿不适。",
                }
            ],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="暑湿不适",
                    evidence="头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="头晕恶心半天，没用药，没有过敏"),
        )
        option = result.treatment_options[0]
        MedicineRepository().update(
            "slot-08-huoxiang-zhengqi",
            {"name": "仓位内已更换的待核验药品"},
        )

        with self.assertRaises(DispenseError) as raised:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=0,
                ),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(dispense.requests, [])
        invalidated = service.get_session(session.session_id)
        self.assertFalse(invalidated.can_view_medicines)
        self.assertEqual(invalidated.treatment_options, [])
        self.assertEqual(
            [notice.code for notice in invalidated.medication_safety_notices],
            ["inventory_changed"],
        )

    def test_reapproved_safety_change_after_display_requires_new_confirmation(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    "label": "主方案",
                    "reason": "更贴近当前的暑湿不适。",
                }
            ],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="暑湿不适",
                    evidence="头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="头晕恶心半天，没用药，没有过敏"),
        )
        option = result.treatment_options[0]
        repository = MedicineRepository()
        medicine = repository.get_by_id("slot-08-huoxiang-zhengqi")
        repository.update(
            medicine.id,
            {
                "dosage": f"{medicine.dosage} 使用前再次核对包装。",
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "test-pharmacist",
                "safety_reviewed_at": "2026-08-08T12:20:00+08:00",
            },
        )

        with self.assertRaises(DispenseError) as raised:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=0,
                ),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(dispense.requests, [])
        invalidated = service.get_session(session.session_id)
        self.assertEqual(invalidated.treatment_options, [])
        self.assertEqual(
            [notice.code for notice in invalidated.medication_safety_notices],
            ["inventory_changed"],
        )

    def test_new_safety_conflict_after_display_fails_closed_with_specific_notice(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-13-ibuprofen"],
                    "label": "主方案",
                    "reason": "与当前轻微头痛相关。",
                }
            ],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="头痛",
                    evidence="逐渐出现的轻微头痛，没有神经危险表现",
                    duration="半天",
                    used="未使用",
                    allergy="青霉素",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="li-yeye")
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="逐渐出现的轻微头痛半天，没用药，对青霉素过敏"
            ),
        )
        option = result.treatment_options[0]
        repository = MedicineRepository()
        medicine = repository.get_by_id("slot-13-ibuprofen")
        repository.update(
            medicine.id,
            {
                "contraindications": [
                    *medicine.contraindications,
                    "青霉素过敏者禁用",
                ],
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "test-pharmacist",
                "safety_reviewed_at": "2026-08-08T12:00:00+08:00",
            },
        )

        with self.assertRaises(DispenseError) as raised:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=0,
                ),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(dispense.requests, [])
        invalidated = service.get_session(session.session_id)
        self.assertEqual(invalidated.treatment_options, [])
        self.assertEqual(
            [notice.code for notice in invalidated.medication_safety_notices],
            ["allergy_conflict"],
        )
        self.assertIn("布洛芬缓释胶囊", invalidated.medication_safety_notices[0].message)

    def test_current_registered_history_is_reloaded_before_opening(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-13-ibuprofen"],
                    "label": "主方案",
                    "reason": "与当前轻微头痛相关。",
                }
            ],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="头痛",
                    evidence="逐渐出现的轻微头痛，没有神经危险表现",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="li-yeye")
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript="逐渐出现的轻微头痛半天，没用药，没有过敏"
            ),
        )
        option = result.treatment_options[0]
        with db.connect() as conn:
            conn.execute(
                "UPDATE service_users SET profile=profile || ? WHERE id=?",
                ("；肾功能不全", "li-yeye"),
            )

        with self.assertRaises(DispenseError) as raised:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=0,
                ),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(dispense.requests, [])
        invalidated = service.get_session(session.session_id)
        self.assertEqual(
            [notice.code for notice in invalidated.medication_safety_notices],
            ["history_contraindication"],
        )

    def test_revoked_combination_after_display_fails_closed_before_hardware(self) -> None:
        dispense = FakeDispenseService()
        service, _ = self.service(
            [low_risk_watery_diarrhea_interpretation()],
            ranking=echo_authorized_diarrhea_combination,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="wang-nainai")
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript=GROUNDED_DIARRHEA_TRANSCRIPT
            ),
        )
        option = result.treatment_options[0]
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE approved_medicine_combinations
                SET review_status='invalidated', updated_at=?
                WHERE combination_id=?
                """,
                (
                    db.now_text(),
                    "candidate-adult-watery-diarrhea-separated-v1",
                ),
            )

        with self.assertRaises(DispenseError) as raised:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=0,
                ),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(dispense.requests, [])
        invalidated = service.get_session(session.session_id)
        self.assertFalse(invalidated.can_view_medicines)
        self.assertEqual(invalidated.treatment_options, [])
        self.assertEqual(
            [notice.code for notice in invalidated.medication_safety_notices],
            ["combination_not_approved"],
        )

    def test_new_reviewed_matrix_block_after_display_fails_closed_before_hardware(self) -> None:
        repository = MedicineRepository()
        dispense = FakeDispenseService()
        service, _ = self.service(
            [low_risk_watery_diarrhea_interpretation()],
            ranking=echo_authorized_diarrhea_combination,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="wang-nainai")
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(
                transcript=GROUNDED_DIARRHEA_TRANSCRIPT
            ),
        )
        option = result.treatment_options[0]
        repository.save_ingredient_conflict(
            left_ingredient="蒙脱石",
            right_ingredient="长型双歧杆菌",
            disposition="block",
            message="该成分组合需要药师重新核对。",
            review_status="reviewed",
            reviewed_by="test-pharmacist",
            reviewed_at="2026-08-08T00:05:00+08:00",
        )

        with self.assertRaises(DispenseError) as raised:
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id=option.option_id,
                    confirmed_safety_notice=True,
                    expected_item_index=0,
                ),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(dispense.requests, [])
        invalidated = service.get_session(session.session_id)
        self.assertFalse(invalidated.can_view_medicines)
        self.assertEqual(invalidated.treatment_options, [])
        self.assertEqual(
            [notice.code for notice in invalidated.medication_safety_notices],
            ["ingredient_conflict"],
        )
        self.assertIn("药师重新核对", invalidated.medication_safety_notices[0].message)

    def test_existing_plan_exposes_and_authorizes_a_prescription_candidate(self) -> None:
        MedicineService().list_medicines()
        plan = next(
            item
            for item in RecordsService().list_today_plans()
            if item.id == "plan-demo-li-desloratadine"
        )
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [{
                "medicine_ids": ["slot-23-desloratadine"],
                "label": "主方案",
                "reason": "按既往医嘱核对口服药。",
            }],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [case(
                action="analyze",
                concept="鼻部过敏不适",
                evidence="接触花粉后连续打喷嚏和鼻塞",
                duration="半天",
                used="未使用",
                allergy="无",
            )],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service, service_user_id="li-yeye")

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="接触花粉后连续打喷嚏和鼻塞，半天了，没用药，没有过敏"),
        )

        medicines = result.treatment_options[0].medicines
        self.assertEqual(
            [medicine.id for medicine in medicines],
            ["slot-23-desloratadine"],
        )
        self.assertTrue(medicines[0].requires_existing_direction)

        response = service.confirm_treatment(
            session.session_id,
            InquiryTreatmentConfirmRequest(
                option_id="A",
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )

        self.assertTrue(response.ok)
        self.assertEqual(dispense.requests[0].medicine_id, "slot-23-desloratadine")
        self.assertEqual(dispense.requests[0].today_plan_id, plan.id)

    def test_alternative_option_can_be_selected_and_opened(self) -> None:
        ranking = {
            "ok": True,
            "source": "cloud",
            "options": [
                {
                    "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    "label": "主方案",
                    "reason": "更贴近暑湿不适。",
                },
                {
                    "medicine_ids": ["slot-12-hydrotalcite"],
                    "label": "备选方案",
                    "reason": "如果胃部不适更明显，可对照这一选择。",
                },
            ],
        }
        dispense = FakeDispenseService()
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="暑湿胃部不适",
                    evidence="头晕并伴有胃部不适",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking=ranking,
            dispense=dispense,
        )
        session = self.create(service)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="头晕并伴有胃部不适半天，没用药，没有过敏"),
        )

        self.assertEqual(len(result.treatment_options), 2)
        response = service.confirm_treatment(
            session.session_id,
            InquiryTreatmentConfirmRequest(
                option_id="B",
                confirmed_safety_notice=True,
                expected_item_index=0,
            ),
        )

        self.assertTrue(response.ok)
        self.assertEqual(dispense.requests[0].medicine_id, "slot-12-hydrotalcite")

    def test_previous_sessions_are_passed_as_natural_history_not_tag_counts(self) -> None:
        first_service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="便秘",
                    evidence="排便困难",
                    duration="两天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={"ok": True, "source": "cloud", "options": []},
        )
        first = self.create(first_service, service_user_id="li-yeye")
        first_service.process_turn(
            first.session_id,
            InquiryTurnRequest(transcript="排便困难两天，没用药，没有过敏"),
        )

        second_service, second_interpreter = self.service(
            [case(action="ask", reply="这次和上次相比有什么变化？")]
        )
        second = self.create(second_service, service_user_id="li-yeye")
        second_service.process_turn(
            second.session_id,
            InquiryTurnRequest(transcript="今天又有点不舒服"),
        )

        history = second_interpreter.contexts[0]["recent_history"]
        self.assertTrue(history)
        self.assertIn("case_summary", history[0])
        self.assertNotIn("dimension_counts", history[0])

    def test_model_recent_history_is_scoped_to_the_current_persona_generation(self) -> None:
        old_service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="旧代次症状",
                    evidence="旧代次症状持续两天",
                    duration="两天",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={"ok": True, "source": "cloud", "options": []},
        )
        old_session = self.create(old_service, service_user_id="li-yeye")
        old_service.process_turn(
            old_session.session_id,
            InquiryTurnRequest(transcript="旧代次症状持续两天，没用药，没有过敏"),
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE service_users SET persona_generation='senior-demo-v2' WHERE id='li-yeye'"
            )

        current_service, current_interpreter = self.service(
            [
                case(
                    action="analyze",
                    concept="新代次症状",
                    evidence="新代次症状持续一天",
                    duration="一天",
                    used="未使用",
                    allergy="无",
                ),
                case(action="ask", reply="请继续说明这次的不适。"),
            ],
            ranking={"ok": True, "source": "cloud", "options": []},
        )
        first_current = self.create(current_service, service_user_id="li-yeye")
        current_service.process_turn(
            first_current.session_id,
            InquiryTurnRequest(transcript="新代次症状持续一天，没用药，没有过敏"),
        )
        second_current = self.create(current_service, service_user_id="li-yeye")
        current_service.process_turn(
            second_current.session_id,
            InquiryTurnRequest(transcript="这次又有一点不舒服"),
        )

        self.assertEqual(current_interpreter.contexts[0]["recent_history"], [])
        later_history = current_interpreter.contexts[1]["recent_history"]
        self.assertEqual(len(later_history), 1)
        self.assertIn("新代次症状", later_history[0]["case_summary"])
        self.assertNotIn("旧代次症状", str(later_history))

    def test_confirmation_still_requires_explicit_safety_acknowledgement(self) -> None:
        service, _ = self.service([])
        session = self.create(service)
        with self.assertRaises(DispenseError):
            service.confirm_treatment(
                session.session_id,
                InquiryTreatmentConfirmRequest(
                    option_id="A",
                    confirmed_safety_notice=False,
                ),
            )

    def test_scope_confirmation_precedes_and_does_not_consume_four_focused_questions(self) -> None:
        service, _ = self.service(
            [
                case(
                    concept="头痛",
                    evidence="太阳穴有点痛",
                    reply="这次头痛是突然达到最痛，还是逐渐出现的？",
                    scope_complete=False,
                ),
                case(
                    concept="头痛",
                    evidence="太阳穴有点痛",
                    reply="这次头痛是突然达到最痛，还是逐渐出现的？",
                    scope_complete=True,
                ),
            ]
        )
        session = self.create(service)
        scope = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我太阳穴有点痛"),
        )
        self.assertIn("其他明显不舒服", scope.reply)
        self.assertEqual(scope.extracted_information.asked_clarifications, [])

        focused = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="没有别的了"),
        )
        self.assertNotIn("其他明显不舒服", focused.reply)
        self.assertEqual(len(focused.extracted_information.asked_clarifications), 1)

    def test_scope_confirmation_precedes_a_model_vitals_request(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="measure_vitals",
                    concept="头晕",
                    evidence="有点头晕",
                    reply="请先测量额温、心率和血氧。",
                    scope_complete=False,
                )
            ]
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我有点头晕"),
        )

        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertIn("其他明显不舒服", result.reply)
        self.assertEqual(result.extracted_information.pending_clarification, "additional_symptoms")

    def test_positive_scope_answer_merges_the_symptom_then_starts_focused_clarification(self) -> None:
        service, _ = self.service(
            [
                case(
                    concept="咽喉疼痛",
                    evidence="嗓子疼",
                    reply="吞咽时会更痛吗？",
                    scope_complete=False,
                ),
                case(
                    concept="发冷",
                    evidence="还有发冷",
                    reply="发冷时有没有量过体温？",
                    scope_complete=True,
                    change_type="add",
                ),
            ]
        )
        session = self.create(service)
        scope = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="我嗓子疼"),
        )
        self.assertEqual(scope.extracted_information.pending_clarification, "additional_symptoms")

        focused = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="还有发冷"),
        )

        present = {
            item.concept
            for item in focused.extracted_information.observations
            if item.status == "present"
        }
        self.assertEqual(present, {"咽喉疼痛", "发冷"})
        self.assertTrue(focused.extracted_information.symptom_scope_confirmed)
        self.assertNotEqual(
            focused.extracted_information.pending_clarification,
            "additional_symptoms",
        )
        self.assertNotIn("其他明显不舒服", focused.reply)
        self.assertEqual(len(focused.extracted_information.asked_clarifications), 1)

    def test_complaint_replacement_preserves_other_symptoms_and_restarts_budget(self) -> None:
        service, _ = self.service(
            [
                case(
                    concept="头痛",
                    evidence="不是头晕，是太阳穴刺痛，嗓子还是疼",
                    reply="这次头痛是突然达到最痛，还是逐渐出现的？",
                    material_change=True,
                    change_type="replace",
                    replaced_concepts=["头晕"],
                    scope_complete=False,
                )
            ]
        )
        session = self.create(service)
        session.extracted_information = InquiryExtractedInformation(
            case_summary="头晕并伴咽喉疼痛",
            observations=[
                InquiryObservation(concept="头晕", status="present", evidence="头晕", source_turn=1, confidence=0.9),
                InquiryObservation(concept="咽喉疼痛", status="present", evidence="嗓子疼", source_turn=1, confidence=0.9),
            ],
            symptoms_text="头晕、咽喉疼痛",
            duration="今天早上开始",
            clarification_answers={"onset": "今天早上开始", "throat_features": "吞咽疼"},
            asked_clarifications=["onset", "throat_features", "severity", "breathing"],
            symptom_scope_confirmed=True,
        )
        service.repository.save_session(session)

        corrected = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="不是头晕，是太阳穴刺痛，嗓子还是疼"),
        )
        concepts = {
            item.concept for item in corrected.extracted_information.observations if item.status == "present"
        }
        self.assertNotIn("头晕", concepts)
        self.assertIn("头痛", concepts)
        self.assertIn("咽喉疼痛", concepts)
        self.assertEqual(corrected.extracted_information.duration, "今天早上开始")
        self.assertEqual(corrected.extracted_information.asked_clarifications, [])
        self.assertEqual(corrected.extracted_information.symptom_revision, 1)
        self.assertIn("其他明显不舒服", corrected.reply)

    def test_material_added_symptom_after_four_followups_restarts_budget(self) -> None:
        service, _ = self.service(
            [
                case(
                    concept="胸痛",
                    evidence="另外刚刚出现胸痛",
                    reply="胸痛时呼吸会觉得费力吗？",
                    change_type="add",
                    scope_complete=False,
                )
            ]
        )
        session = self.create(service)
        session.extracted_information = InquiryExtractedInformation(
            case_summary="头晕持续一小时",
            observations=[
                InquiryObservation(
                    concept="头晕",
                    status="present",
                    evidence="头晕",
                    source_turn=1,
                    confidence=0.9,
                )
            ],
            symptoms_text="头晕",
            duration="一小时",
            clarification_answers={
                "onset": "一小时",
                "symptom_detail": "眼前发黑",
                "fever": "没量",
                "severity": "明显",
            },
            asked_clarifications=["onset", "symptom_detail", "fever", "severity"],
            pending_clarification="severity",
            symptom_scope_confirmed=True,
        )
        service.repository.save_session(session)

        added = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="另外刚刚出现胸痛"),
        )

        self.assertIn("头晕", added.extracted_information.symptoms_text)
        self.assertIn("胸痛", added.extracted_information.symptoms_text)
        self.assertEqual(added.extracted_information.asked_clarifications, [])
        self.assertEqual(added.extracted_information.symptom_revision, 1)
        self.assertIn("其他明显不舒服", added.reply)

    def test_refining_existing_symptom_does_not_restart_spent_budget(self) -> None:
        service, _ = self.service(
            [
                case(
                    concept="头晕",
                    evidence="更准确说是天旋地转",
                    reply="还要无限追问吗？",
                    change_type="refine",
                    scope_complete=True,
                )
            ]
        )
        session = self.create(service)
        session.extracted_information = InquiryExtractedInformation(
            case_summary="头晕持续一小时",
            observations=[
                InquiryObservation(
                    concept="头晕",
                    status="present",
                    evidence="头晕",
                    source_turn=1,
                    confidence=0.9,
                )
            ],
            symptoms_text="头晕",
            duration="一小时",
            clarification_answers={
                "onset": "一小时",
                "symptom_detail": "眼前发黑",
                "fever": "没量",
                "severity": "明显",
            },
            asked_clarifications=["onset", "symptom_detail", "fever", "severity"],
            pending_clarification="severity",
            symptom_scope_confirmed=True,
        )
        service.repository.save_session(session)

        refined = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="更准确说是天旋地转"),
        )

        self.assertEqual(len(refined.extracted_information.asked_clarifications), 4)
        self.assertEqual(refined.extracted_information.symptom_revision, 0)
        self.assertIn("吃过", refined.reply)

    def test_final_assessment_maps_only_known_evidence_ids(self) -> None:
        assessment = InquiryOrchestrator._assessment_from_ranking(
            {
                "assessment": {
                    "summary": "现有表现较符合常见上呼吸道感染。",
                    "possible_conditions": [
                        {
                            "name": "急性上呼吸道感染",
                            "likelihood": "more_likely",
                            "supporting_evidence_ids": ["obs-1", "invented"],
                            "non_supporting_evidence_ids": ["vital-temperature"],
                        }
                    ],
                    "next_steps": ["休息并补充水分"],
                    "seek_care_if": ["高热或呼吸困难"],
                }
            },
            {"obs-1": "咽喉疼痛：存在", "vital-temperature": "本次额温：36.8℃"},
        )
        condition = assessment.possible_conditions[0]
        self.assertEqual(condition.supporting_evidence, ["咽喉疼痛：存在"])
        self.assertEqual(condition.non_supporting_evidence, ["本次额温：36.8℃"])
        self.assertIn("急性上呼吸道感染", assessment.summary)

    def test_completed_turn_does_not_expose_model_generated_medication_directions(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="暑热后胃肠不适",
                    evidence="晒后头晕恶心",
                    duration="半天",
                    used="未使用",
                    allergy="无",
                    risk="medium",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "assessment": {
                    "possible_conditions": [],
                    "next_steps": [
                        "服用布洛芬1片，每日3次",
                        "建议使用阿莫西林胶囊",
                        "症状持续时再服阿莫西林2粒",
                    ],
                    "seek_care_if": [
                        "持续呕吐，吃不下东西",
                        "症状持续时再服阿莫西林2粒",
                        "吃一片芬必得",
                    ],
                },
                "options": [
                    {
                        "label": "主方案",
                        "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    }
                ],
            },
        )

        result = service.process_turn(
            self.create(service).session_id,
            InquiryTurnRequest(transcript="晒后头晕恶心半天，没用药，没有过敏"),
        )

        self.assertEqual(
            result.extracted_information.final_assessment.next_steps,
            [],
        )
        self.assertEqual(
            result.extracted_information.final_assessment.seek_care_if,
            ["持续呕吐，吃不下东西"],
        )

    def test_final_assessment_summary_does_not_turn_unknown_fever_into_absence(self) -> None:
        assessment = InquiryOrchestrator._assessment_from_ranking(
            {
                "assessment": {
                    "summary": "患者无发热，考虑急性咽炎。",
                    "possible_conditions": [
                        {
                            "name": "急性咽炎",
                            "likelihood": "more_likely",
                            "supporting_evidence_ids": ["obs-1"],
                            "non_supporting_evidence_ids": ["obs-2"],
                        }
                    ],
                    "next_steps": ["测量体温"],
                    "seek_care_if": ["高热或呼吸困难"],
                }
            },
            {
                "obs-1": "咽痛：存在（嗓子疼）",
                "obs-2": "发热：尚不确定（还没量体温）",
                "vital-status": "本次体征：测量未完成",
            },
        )

        self.assertNotIn("无发热", assessment.summary)
        self.assertIn("急性咽炎", assessment.summary)
        self.assertIn("发热", assessment.summary)
        self.assertIn("本次体征", assessment.summary)

    def test_final_assessment_drops_diagnosis_dosing_and_hardware_instructions(self) -> None:
        assessment = InquiryOrchestrator._assessment_from_ranking(
            {
                "assessment": {
                    "possible_conditions": [],
                    "next_steps": [
                        "少量多次补水并观察症状变化",
                        "已经确诊感冒，可自行服用布洛芬2片",
                        "直接打开13号药柜取药",
                    ],
                    "seek_care_if": [
                        "出现呼吸困难或意识变化",
                        "症状加重时开柜加倍服药",
                    ],
                }
            },
            {"obs-1": "咽痛：存在"},
        )

        self.assertEqual(assessment.next_steps, ["少量多次补水并观察症状变化"])
        self.assertEqual(assessment.seek_care_if, ["出现呼吸困难或意识变化"])

    def test_final_assessment_removes_diagnostic_certainty_from_condition_names(self) -> None:
        assessment = InquiryOrchestrator._assessment_from_ranking(
            {
                "assessment": {
                    "possible_conditions": [
                        {
                            "name": "已经确诊为急性咽炎",
                            "likelihood": "more_likely",
                            "supporting_evidence_ids": ["obs-1"],
                        },
                        {
                            "name": "打开药柜服药",
                            "likelihood": "possible",
                            "supporting_evidence_ids": ["obs-1"],
                        },
                    ]
                }
            },
            {"obs-1": "咽痛：存在"},
        )

        self.assertEqual(
            [condition.name for condition in assessment.possible_conditions],
            ["急性咽炎"],
        )


if __name__ == "__main__":
    unittest.main()
