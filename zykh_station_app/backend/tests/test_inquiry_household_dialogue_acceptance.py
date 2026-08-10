from __future__ import annotations

import re
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.schemas.inquiry import (  # noqa: E402
    InquiryObservation,
    InquirySessionCreateRequest,
    InquiryTurnRequest,
    InquiryVitalsRequest,
)
from app.services.ai_service import AiService  # noqa: E402
from app.services.inquiry_orchestrator import InquiryOrchestrator  # noqa: E402
from app.services.symptom_interpreter import SymptomInterpretation, SymptomInterpreter  # noqa: E402


@dataclass(frozen=True)
class HouseholdDialogue:
    label: str
    marker: str
    concept: str
    evidence: str
    duration: str
    service_user_id: str
    allergy: str = "无"
    ranking_fails: bool = False

    @property
    def first_turn(self) -> str:
        return (
            f"{self.evidence}，已经{self.duration}，这次还没有用药，"
            f"药物过敏或禁忌是{self.allergy}。整体症状轻微，没有发热，呼吸正常，"
            "能正常喝水，大便也没有异常颜色"
        )


DIALOGUES = (
    HouseholdDialogue(
        label="过敏性鼻炎",
        marker="鼻塞流涕",
        concept="过敏性鼻炎不适",
        evidence="鼻塞流涕并打喷嚏",
        duration="两天",
        service_user_id="zhangsan",
        allergy="青霉素过敏",
    ),
    HouseholdDialogue(
        label="轻微感冒",
        marker="轻微感冒",
        concept="感冒样不适",
        evidence="轻微感冒伴流鼻涕",
        duration="一天",
        service_user_id="lisi",
    ),
    HouseholdDialogue(
        label="咳嗽咽痒",
        marker="干咳咽痒",
        concept="咳嗽咽喉不适",
        evidence="干咳咽痒但呼吸正常",
        duration="三天",
        service_user_id="",
    ),
    HouseholdDialogue(
        label="咽喉不适",
        marker="轻微咽痛",
        concept="咽喉不适",
        evidence="吞咽时有轻微咽痛",
        duration="一天",
        service_user_id="zhangsan",
    ),
    HouseholdDialogue(
        label="急性腹泻",
        marker="稀便腹泻",
        concept="腹泻",
        evidence="稀便腹泻但能正常喝水",
        duration="半天",
        service_user_id="lisi",
    ),
    HouseholdDialogue(
        label="胃酸反流",
        marker="反酸烧心",
        concept="胃部不适",
        evidence="饭后反酸烧心",
        duration="两天",
        service_user_id="",
        allergy="磺胺类药物过敏",
    ),
    HouseholdDialogue(
        label="便秘",
        marker="排便困难",
        concept="便秘",
        evidence="排便困难但没有剧烈腹痛",
        duration="三天",
        service_user_id="zhangsan",
    ),
    HouseholdDialogue(
        label="轻微擦伤",
        marker="表皮擦伤",
        concept="轻微擦伤",
        evidence="手臂表皮擦伤并且已经止血",
        duration="两小时",
        service_user_id="lisi",
    ),
    HouseholdDialogue(
        label="轻微扭伤",
        marker="轻微扭伤",
        concept="轻微扭伤",
        evidence="脚踝轻微扭伤但还能正常活动",
        duration="一天",
        service_user_id="",
    ),
    HouseholdDialogue(
        label="皮肤瘙痒",
        marker="局部瘙痒",
        concept="局部皮肤不适",
        evidence="手背局部瘙痒且没有明显红肿",
        duration="两天",
        service_user_id="zhangsan",
    ),
    HouseholdDialogue(
        label="口腔不适匹配可重试",
        marker="口腔溃疡",
        concept="口腔不适",
        evidence="轻微口腔溃疡",
        duration="两天",
        service_user_id="lisi",
        ranking_fails=True,
    ),
)


class AcceptanceInterpreter:
    def __init__(self) -> None:
        self.contexts: list[dict] = []
        self.rank_contexts: list[dict] = []
        self.failed_rankings: set[str] = set()

    @staticmethod
    def opening_question(_profile: dict, fallback: str) -> tuple[str, str]:
        return fallback, "acceptance_fake"

    def interpret(self, transcript: str, existing: dict, _profile: dict) -> SymptomInterpretation:
        self.contexts.append(existing)
        dialogue = self._dialogue_for(transcript, existing)
        topic = self._topic_for(dialogue)
        evidence_by_topic = {
            "severity": "整体症状轻微，未影响基本活动",
            "symptom_detail": dialogue.evidence,
            topic: dialogue.evidence,
            "fever": "没有发热",
            "breathing": "没有呼吸费力",
            "dehydration": "能够正常喝水",
            "stool_features": "没有便血或黑便",
        }
        return SymptomInterpretation(
            case_summary=f"{dialogue.label}：{dialogue.evidence}，持续{dialogue.duration}。",
            observations=[
                InquiryObservation(
                    concept=dialogue.concept,
                    status="present",
                    evidence=dialogue.evidence,
                    source_turn=max(int(existing.get("conversation_turns") or 1), 1),
                    confidence=0.95,
                )
            ],
            duration=dialogue.duration,
            used_medicines="未使用",
            allergy_or_contraindication=dialogue.allergy,
            assistant_reply="我会根据已经确认的信息继续判断。",
            reasoning_summary=f"已确认{dialogue.evidence}。",
            action_intent="analyze",
            action_reason="家庭常见不适信息已经完整",
            ai_risk_level="low",
            answered_topics_this_turn=list(evidence_by_topic),
            topic_evidence=evidence_by_topic,
            clinical_ready=True,
            symptom_scope_complete="没有其他明显不舒服" in transcript,
            confidence=0.95,
            source="acceptance_fake",
            available=True,
        )

    def rank_candidates(self, context: dict, candidates: list[dict]) -> dict:
        self.rank_contexts.append(context)
        dialogue = next(
            item for item in DIALOGUES if item.label in str(context.get("case_summary") or "")
        )
        if dialogue.ranking_fails and dialogue.label not in self.failed_rankings:
            self.failed_rankings.add(dialogue.label)
            return {
                "ok": False,
                "source": "acceptance_fake",
                "message": "验收假件模拟一次不稳定返回",
            }
        options = []
        if candidates:
            options.append(
                {
                    "medicine_ids": [candidates[0]["id"]],
                    "label": f"{dialogue.label}家庭护理选择",
                    "reason": "仅用于验证库存约束后的方案不会跨会话残留。",
                }
            )
        return {
            "ok": True,
            "source": "acceptance_fake",
            "assessment": {
                "summary": "家庭常见轻症，当前先观察变化。",
                "possible_conditions": [
                    {
                        "name": dialogue.label,
                        "likelihood": "possible",
                        "supporting_evidence_ids": ["obs-1"],
                        "non_supporting_evidence_ids": [],
                    }
                ],
                "next_steps": ["休息并观察症状变化"],
                "seek_care_if": ["症状持续加重时联系医生"],
            },
            "options": options,
        }

    @staticmethod
    def _dialogue_for(transcript: str, existing: dict) -> HouseholdDialogue:
        for dialogue in DIALOGUES:
            if dialogue.marker in transcript:
                return dialogue
        concepts = {
            str(item.get("concept") or "")
            for item in existing.get("observations") or []
            if isinstance(item, dict)
        }
        for dialogue in DIALOGUES:
            if dialogue.concept in concepts:
                return dialogue
        raise AssertionError(f"验收假件无法识别当前对话：{transcript}")

    @staticmethod
    def _topic_for(dialogue: HouseholdDialogue) -> str:
        if any(term in dialogue.concept for term in ("鼻炎", "感冒", "咳嗽")):
            return "respiratory_features"
        if "咽喉" in dialogue.concept or "口腔" in dialogue.concept:
            return "throat_features"
        if any(term in dialogue.concept for term in ("腹泻", "便秘", "胃")):
            return "digestive_features"
        if any(term in dialogue.concept for term in ("擦伤", "扭伤")):
            return "injury_features"
        return "skin_features"


class NoHardwareDispense:
    def confirm(self, _request):
        raise AssertionError("验收对话不允许触发真实或模拟开柜")


class InMemoryGuestArchive:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def schedule_capture(self, session_id: str, guest_name: str) -> None:
        self.requests.append((session_id, guest_name))


class HouseholdDialogueAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "household-dialogues.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        self.interpreter = AcceptanceInterpreter()
        self.guest_archive = InMemoryGuestArchive()
        self.service = InquiryOrchestrator(
            interpreter=self.interpreter,
            dispense_service=NoHardwareDispense(),
            guest_archive_service=self.guest_archive,
        )

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_eleven_household_dialogues_complete_without_cross_session_state(self) -> None:
        prior_concepts: list[str] = []
        prior_allergies: list[str] = []
        session_ids: set[str] = set()

        for index, dialogue in enumerate(DIALOGUES, start=1):
            with self.subTest(index=index, dialogue=dialogue.label):
                session = self.service.create_session(
                    InquirySessionCreateRequest(
                        service_user_id=dialogue.service_user_id,
                        guest_name=f"验收访客{index}",
                    )
                )
                self.assertNotIn(session.session_id, session_ids)
                session_ids.add(session.session_id)
                self.assertEqual(session.extracted_information.symptoms_text, "")
                self.assertEqual(
                    session.extracted_information.allergy_or_contraindication,
                    session.user_allergies,
                )
                self.assertEqual(session.treatment_options, [])

                scoped = self.service.process_turn(
                    session.session_id,
                    InquiryTurnRequest(transcript=dialogue.first_turn),
                )
                self.assertEqual(scoped.stage, "clarification")
                self.assertIn("其他明显不舒服", scoped.reply)

                terminal = self.service.process_turn(
                    session.session_id,
                    InquiryTurnRequest(transcript="没有其他明显不舒服"),
                )
                if dialogue.ranking_fails:
                    self.assertEqual(terminal.session_id, session.session_id)
                    self.assertEqual(terminal.stage, "clarification")
                    self.assertEqual(terminal.next_action, "ask")
                    self.assertIn("重新匹配", terminal.reply)
                    terminal = self.service.process_turn(
                        session.session_id,
                        InquiryTurnRequest(transcript="请重新匹配"),
                    )

                self.assertEqual(terminal.session_id, session.session_id)
                self.assertEqual(terminal.stage, "result")
                self.assertIn(
                    terminal.next_action,
                    {"show_recommendation", "complete", "escalate"},
                )
                observation_concepts = {
                    observation.concept
                    for observation in terminal.extracted_information.observations
                }
                self.assertIn(dialogue.concept, observation_concepts)
                self.assertEqual(
                    terminal.extracted_information.allergy_or_contraindication,
                    dialogue.allergy,
                )
                for concept in prior_concepts:
                    self.assertNotIn(concept, observation_concepts)
                for allergy in prior_allergies:
                    if allergy != "无" and allergy != dialogue.allergy:
                        self.assertNotIn(
                            allergy,
                            terminal.extracted_information.allergy_or_contraindication,
                        )
                for option in terminal.treatment_options:
                    self.assertIn(dialogue.label, option.label)
                self._assert_no_repeated_questions(terminal)
                prior_concepts.append(dialogue.concept)
                prior_allergies.append(dialogue.allergy)

        self.assertGreaterEqual(len(session_ids), 10)

    def test_ten_household_dialogues_never_use_rules_to_select_medicines(self) -> None:
        cloud_required_settings = SimpleNamespace(
            ai_mode="cloud",
            offline_inquiry_mode="rules",
            ai_api_key="",
            ai_api_key_file=Path("/nonexistent"),
        )
        prior_first_turns: list[str] = []
        session_ids: set[str] = set()

        with patch("app.services.ai_service.settings", cloud_required_settings):
            service = InquiryOrchestrator(
                interpreter=SymptomInterpreter(ai_service=AiService()),
                dispense_service=NoHardwareDispense(),
                guest_archive_service=self.guest_archive,
            )
            for index, dialogue in enumerate(DIALOGUES[:10], start=1):
                with self.subTest(index=index, dialogue=dialogue.label):
                    session = service.create_session(
                        InquirySessionCreateRequest(
                            service_user_id=dialogue.service_user_id,
                            guest_name=f"真实离线验收访客{index}",
                        )
                    )
                    self.assertNotIn(session.session_id, session_ids)
                    session_ids.add(session.session_id)

                    transcript = dialogue.first_turn
                    for _turn in range(8):
                        session = service.process_turn(
                            session.session_id,
                            InquiryTurnRequest(transcript=transcript),
                        )
                        if "重新匹配" in session.reply:
                            break
                        if session.next_action == "measure_vitals":
                            session = service.attach_vitals(
                                session.session_id,
                                InquiryVitalsRequest(
                                    status="cancelled",
                                    error_message="隔离验收不读取硬件",
                                ),
                            )
                        transcript = self._offline_answer(session.reply)

                    self.assertIn(session.stage, {"clarification", "result"})
                    if session.stage == "clarification":
                        self.assertEqual(session.next_action, "ask")
                        self.assertIn("重新匹配", session.reply)
                    else:
                        self.assertEqual(session.next_action, "complete")
                        self.assertIn("没有检测到合适药物", session.reply)
                    self.assertFalse(session.can_view_medicines)
                    self.assertEqual(session.treatment_options, [])
                    current_user_messages = [
                        message.content
                        for message in session.messages
                        if message.role == "user"
                    ]
                    self.assertIn(dialogue.first_turn, current_user_messages)
                    for prior_first_turn in prior_first_turns:
                        self.assertNotIn(prior_first_turn, current_user_messages)
                    self._assert_no_repeated_questions(session)
                    prior_first_turns.append(dialogue.first_turn)

        self.assertEqual(len(session_ids), 10)

    @staticmethod
    def _offline_answer(reply: str) -> str:
        if "其他明显不舒服" in reply:
            return "没有其他明显不舒服"
        if any(term in reply for term in ("用过药", "吃过", "用药")):
            return "没吃"
        if any(term in reply for term in ("过敏", "禁忌", "不能使用")):
            return "无"
        if any(term in reply for term in ("什么时候", "多久")):
            return "今天早上开始"
        if any(term in reply for term in ("发热", "体温")):
            return "没有发热"
        if "呼吸" in reply:
            return "没有呼吸费力"
        if any(term in reply for term in ("严重", "程度")):
            return "症状轻微，不影响正常活动"
        return "没有，整体症状轻微"

    def _assert_no_repeated_questions(self, session) -> None:
        questions = [
            re.sub(r"\s+", "", clause)
            for message in session.messages
            if message.role == "assistant"
            for clause in re.findall(r"[^。！？!?]*[？?]", message.content)
        ]
        self.assertEqual(
            questions,
            list(dict.fromkeys(questions)),
            f"会话出现重复问句：{questions}",
        )


if __name__ == "__main__":
    unittest.main()
