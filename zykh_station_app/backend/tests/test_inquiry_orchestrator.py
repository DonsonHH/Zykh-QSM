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
    InquiryInformationRevisionRequest,
    InquiryObservation,
    InquirySessionCreateRequest,
    InquiryTreatmentConfirmRequest,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from app.services.dispense_service import DispenseError  # noqa: E402
from app.services.inquiry_orchestrator import InquiryOrchestrator  # noqa: E402
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
) -> SymptomInterpretation:
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
        confidence=0.9,
        source="cloud",
        available=True,
    )


class FakeInterpreter:
    def __init__(self, results: list[SymptomInterpretation], ranking: dict | None = None) -> None:
        self.results = list(results)
        self.ranking = ranking or {"ok": True, "source": "cloud", "options": []}
        self.contexts: list[dict] = []
        self.rank_candidates_seen: list[dict] = []

    def opening_question(self, _profile, fallback):
        return fallback, "assistant"

    def interpret(self, _transcript, existing, _profile):
        self.contexts.append(existing)
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

    def rank_candidates(self, context, candidates):
        self.rank_candidates_seen.append({"context": context, "candidates": candidates})
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

    def create(self, service: InquiryOrchestrator):
        return service.create_session(InquirySessionCreateRequest(service_user_id="zhangsan"))

    def test_registered_identity_is_loaded_once_per_session(self) -> None:
        service, _ = self.service([])
        session = self.create(service)

        self.assertEqual(session.user_name, "张三")
        self.assertEqual(session.stage, "symptoms")
        self.assertEqual(service.get_session(session.session_id).user_id, "zhangsan")

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

    def test_symptom_followups_are_capped_at_three_before_core_safety_questions(self) -> None:
        service, _ = self.service(
            [
                case(reply="有没有恶心或明显出汗？"),
                case(reply="头晕是旋转感还是站立不稳？"),
                case(reply="休息和补水以后有没有缓解？"),
                case(reply="现在还有没有乏力或头痛？"),
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
            InquiryTurnRequest(transcript="有一点恶心，也出了汗"),
        )
        third = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="主要是站起来时有点晕"),
        )
        capped = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="休息以后稍微好一点"),
        )

        self.assertIn("恶心", first.reply)
        self.assertIn("旋转感", second.reply)
        self.assertIn("补水", third.reply)
        self.assertNotIn("乏力", capped.reply)
        self.assertIn("过敏", capped.reply)
        self.assertEqual(capped.stage, "clarification")
        self.assertEqual(capped.next_action, "ask")

    def test_capped_flow_advances_through_safety_questions_vitals_and_recommendation(self) -> None:
        service, _ = self.service(
            [
                case(reply="症状问题一？"),
                case(reply="症状问题二？"),
                case(reply="症状问题三？"),
                case(reply="不应出现的症状问题四？"),
                case(reply="模型仍想追问", allergy="无"),
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
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )
        for transcript in ("中暑头晕", "有点恶心", "站起来更晕", "休息后稍好"):
            result = service.process_turn(
                session.session_id,
                InquiryTurnRequest(transcript=transcript),
            )
        self.assertIn("过敏", result.reply)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="也没有"),
        )
        self.assertIn("用过药", result.reply)
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="还没有用过药"),
        )
        self.assertEqual(result.next_action, "measure_vitals")

        result = service.attach_vitals(
            session.session_id,
            InquiryVitalsRequest(
                status="complete",
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
                case(reply="症状问题一？"),
                case(reply="症状问题二？"),
                case(reply="症状问题三？"),
                unavailable,
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )

        for transcript in ("中暑头晕", "有点恶心", "站起来更晕"):
            service.process_turn(
                session.session_id,
                InquiryTurnRequest(transcript=transcript),
            )
        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="休息后稍微好一点"),
        )

        self.assertEqual(result.next_action, "ask")
        self.assertIn("过敏", result.reply)
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
                case(reply="症状问题一？"),
                case(reply="症状问题二？"),
                case(reply="症状问题三？"),
                case(reply="不应出现的症状问题四？"),
                unavailable,
            ]
        )
        session = service.create_session(
            InquirySessionCreateRequest(service_user_id="", guest_name="访客")
        )

        for transcript in ("中暑头晕", "有点恶心", "站起来更晕", "休息后稍好"):
            result = service.process_turn(
                session.session_id,
                InquiryTurnRequest(transcript=transcript),
            )
        self.assertIn("过敏", result.reply)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="也没有"),
        )

        self.assertEqual(result.extracted_information.allergy_or_contraindication, "无")
        self.assertIn("用过药", result.reply)
        self.assertNotIn("换一种说法", result.reply)

    def test_main_complaint_stays_concise_instead_of_accumulating_every_answer(self) -> None:
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
                    reply="有没有恶心或站立不稳？",
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

        self.assertEqual(first.extracted_information.symptoms_text, "头晕")
        self.assertEqual(second.extracted_information.symptoms_text, "头晕")
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
            InquiryVitalsRequest(temperature=36.5, heart_rate=76, spo2=98),
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
        self.assertEqual(result.reply, "请先说说现在最明显的不舒服是什么。")

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
        self.assertIn("再说一次", result.reply)
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
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    duration="半天",
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
            InquiryTurnRequest(transcript="有点不舒服半天，没用药，没有过敏"),
        )

        self.assertEqual(result.stage, "clarification")
        self.assertEqual(result.next_action, "ask")
        self.assertIn("最希望先处理", result.reply)
        self.assertNotIn("连接", result.reply)
        self.assertFalse(result.can_view_medicines)
        self.assertEqual(result.treatment_options, [])

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
        service, interpreter = self.service(
            [
                case(
                    action="end",
                    concept="手部浅表刀伤",
                    evidence="手部刀伤不深，出血已经止住",
                    reply="伤口目前风险较低，注意清洁和覆盖。",
                    duration="刚发生",
                    used="未使用",
                    allergy="无",
                )
            ],
            ranking={
                "ok": True,
                "source": "cloud",
                "options": [
                    {
                        "label": "清洁与覆盖",
                        "reason": "伤口较浅且已经止血，可先完成清洁消毒和覆盖保护。",
                        "medicine_ids": [
                            "slot-17-iodophor",
                            "slot-22-cotton-swab",
                            "slot-10-gauze",
                        ],
                    }
                ],
            },
        )
        session = self.create(service)

        result = service.process_turn(
            session.session_id,
            InquiryTurnRequest(transcript="手部刀伤不深，出血已经止住，没有用药也没有过敏"),
        )

        self.assertEqual(result.next_action, "show_recommendation")
        self.assertTrue(result.can_view_medicines)
        self.assertEqual(
            [medicine.id for medicine in result.treatment_options[0].medicines],
            ["slot-17-iodophor", "slot-22-cotton-swab", "slot-10-gauze"],
        )
        self.assertTrue(interpreter.rank_candidates_seen)

    def test_low_risk_without_a_matching_candidate_returns_neutral_care_advice(self) -> None:
        service, _ = self.service(
            [
                case(
                    action="analyze",
                    concept="轻微擦伤",
                    evidence="膝盖表皮轻微擦伤",
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
            InquiryTurnRequest(transcript="膝盖表皮轻微擦伤，没有用药也没有过敏"),
        )

        self.assertEqual(result.risk_level, "low")
        self.assertEqual(result.stage, "result")
        self.assertEqual(result.next_action, "complete")
        self.assertIn("基础护理", result.reply)
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
        first = self.create(first_service)
        first_service.process_turn(
            first.session_id,
            InquiryTurnRequest(transcript="排便困难两天，没用药，没有过敏"),
        )

        second_service, second_interpreter = self.service(
            [case(action="ask", reply="这次和上次相比有什么变化？")]
        )
        second = self.create(second_service)
        second_service.process_turn(
            second.session_id,
            InquiryTurnRequest(transcript="今天又有点不舒服"),
        )

        history = second_interpreter.contexts[0]["recent_history"]
        self.assertTrue(history)
        self.assertIn("case_summary", history[0])
        self.assertNotIn("dimension_counts", history[0])

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


if __name__ == "__main__":
    unittest.main()
