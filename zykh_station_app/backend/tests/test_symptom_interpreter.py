from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.symptom_interpreter import SymptomInterpreter  # noqa: E402


class OpenCaseAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "cloud",
            "case_summary": "起身时出现短暂眼前发黑，已经持续两天。",
            "observations": [
                {
                    "concept": "体位变化相关不适",
                    "status": "present",
                    "evidence": "起身时眼前会突然黑一下",
                    "source_turn": 3,
                    "confidence": 0.92,
                },
                {
                    "concept": "持续胸痛",
                    "status": "absent",
                    "evidence": "没有胸痛",
                    "source_turn": 3,
                    "confidence": 0.97,
                },
            ],
            "uncertainties": ["是否伴随心悸尚未确认"],
            "history_relationship": {
                "related": True,
                "similarities": ["与上月短暂头晕相似"],
                "important_changes": ["本次主要发生在起身时"],
                "should_reuse_previous_conclusion": False,
            },
            "duration": "两天",
            "used_medicines": "未使用",
            "allergy_or_contraindication": "头孢过敏",
            "next_action": "measure_vitals",
            "next_question": "",
            "assistant_reply": "起身时眼前发黑需要结合体征再判断，请先测量额温、心率和血氧。",
            "reason": "体位变化与循环状态可能相关",
            "risk_level": "medium",
            "risk_signals": ["起身诱发"],
            "confidence": 0.91,
        }


class SemanticEvidenceAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "local_llm",
            "case_summary": "用户描述咽部灼热，但原话没有使用医学术语。",
            "observations": [
                {
                    "concept": "咽部灼热不适",
                    "status": "present",
                    "evidence": "嗓子像火烧一样",
                    "source_turn": 1,
                    "confidence": 0.88,
                }
            ],
            "uncertainties": [],
            "next_action": "ask",
            "next_question": "这种感觉持续多久了？",
            "assistant_reply": "我记下了嗓子灼热的感觉。这种感觉持续多久了？",
            "risk_level": "low",
            "confidence": 0.88,
        }


class UnavailableAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": False,
            "source": "ai_unavailable",
            "message": "云端与本地问询模型当前都不可用。",
        }


class InvalidActionAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "cloud",
            "case_summary": "轻微不适。",
            "observations": [],
            "next_action": "open_cabinet",
            "assistant_reply": "准备打开药柜。",
            "confidence": 0.8,
        }


class StaleDurationQuestionAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "local_llm",
            "case_summary": "晒后头晕恶心。",
            "observations": [
                {
                    "concept": "头晕恶心",
                    "status": "present",
                    "evidence": "晒后头晕恶心",
                    "source_turn": 2,
                    "confidence": 0.82,
                }
            ],
            "duration": "",
            "used_medicines": "",
            "allergy_or_contraindication": "",
            "next_action": "ask",
            "next_question": "头晕持续多久了？",
            "assistant_reply": "头晕持续多久了？",
            "risk_level": "low",
            "confidence": 0.82,
        }


class MisreadContextualNoAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "local_llm",
            "case_summary": "没有",
            "observations": [
                {
                    "concept": "头晕",
                    "status": "present",
                    "evidence": "没有",
                    "source_turn": 4,
                    "confidence": 0.72,
                },
                {
                    "concept": "暑湿不适",
                    "status": "present",
                    "evidence": "没有",
                    "source_turn": 4,
                    "confidence": 0.66,
                },
            ],
            "duration": "",
            "used_medicines": "",
            "allergy_or_contraindication": "",
            "next_action": "ask",
            "next_question": "请问您现在感觉如何？",
            "assistant_reply": "请问您现在感觉如何？",
            "risk_level": "low",
            "confidence": 0.72,
        }


class SymptomInterpreterTest(unittest.TestCase):
    def test_open_case_keeps_a_concept_outside_any_fixed_symptom_whitelist(self) -> None:
        result = SymptomInterpreter(ai_service=OpenCaseAiService()).interpret(
            "起身时眼前会突然黑一下，已经两天了，没有胸痛，没用药，头孢过敏",
            {"conversation_turns": 3},
        )

        self.assertTrue(result.available)
        self.assertEqual(result.case_summary, "起身时出现短暂眼前发黑，已经持续两天。")
        self.assertEqual(result.observations[0].concept, "体位变化相关不适")
        self.assertEqual(result.observations[0].source_turn, 3)
        self.assertEqual(result.action_intent, "measure_vitals")
        self.assertEqual(result.ai_risk_level, "medium")
        self.assertTrue(result.history_relationship.related)

    def test_semantic_concept_does_not_need_to_be_an_exact_transcript_substring(self) -> None:
        result = SymptomInterpreter(ai_service=SemanticEvidenceAiService()).interpret(
            "嗓子像火烧一样",
            {"conversation_turns": 1},
        )

        self.assertEqual(result.observations[0].concept, "咽部灼热不适")
        self.assertEqual(result.observations[0].evidence, "嗓子像火烧一样")
        self.assertEqual(result.follow_up_question, "这种感觉持续多久了？")
        self.assertEqual(result.source, "local_llm")

    def test_model_unavailability_is_not_replaced_with_keyword_inference(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret(
            "我中暑头晕半天了，还没有用药，对头孢过敏"
        )

        self.assertFalse(result.available)
        self.assertEqual(result.source, "assistant")
        self.assertEqual(result.action_intent, "ask")
        self.assertIn("再说一次", result.assistant_reply)
        self.assertNotIn("模型", result.assistant_reply)
        self.assertNotIn("规则", result.assistant_reply)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.symptom_dimensions, [])

    def test_model_cannot_request_a_hardware_action(self) -> None:
        result = SymptomInterpreter(ai_service=InvalidActionAiService()).interpret("有点不舒服")

        self.assertEqual(result.action_intent, "ask")
        self.assertNotIn("打开药柜", result.assistant_reply)

    def test_short_spoken_answers_remain_available_for_review_edits(self) -> None:
        self.assertEqual(SymptomInterpreter.duration_answer("已经两天半了"), "两天半")
        self.assertEqual(
            SymptomInterpreter.used_medicine_answer("还没用过药"),
            "未使用",
        )
        self.assertEqual(
            SymptomInterpreter.allergy_answer("我对头孢过敏"),
            "头孢过敏",
        )

    def test_contextual_spoken_negative_answers_are_understood(self) -> None:
        for transcript in ("这些都还没有", "都没有", "也没有", "我说没有你耳朵聋吗"):
            with self.subTest(transcript=transcript):
                self.assertEqual(
                    SymptomInterpreter.allergy_answer(transcript, allow_short_answer=True),
                    "无",
                )

    def test_explicit_answers_fill_small_model_omissions_without_repeating_question(self) -> None:
        result = SymptomInterpreter(ai_service=StaleDurationQuestionAiService()).interpret(
            "大概半天了，还没有使用药物",
            {"conversation_turns": 2},
        )

        self.assertEqual(result.duration, "半天")
        self.assertEqual(result.used_medicines, "未使用")
        self.assertEqual(result.follow_up_question, "有没有药物过敏或明确不能使用的药？")
        self.assertEqual(result.assistant_reply, result.follow_up_question)

    def test_short_no_is_bound_to_the_previous_medicine_question(self) -> None:
        existing = {
            "conversation_turns": 4,
            "case_summary": "暑热后头晕，已经持续半天多。",
            "duration": "半天多",
            "used_medicines": "",
            "allergy_or_contraindication": "",
            "conversation": [
                {"role": "user", "content": "我有些中暑头晕"},
                {"role": "assistant", "content": "这种不舒服大概持续多久了？"},
                {"role": "user", "content": "半天多"},
                {"role": "assistant", "content": "这次不舒服以后有没有用过药？"},
            ],
        }

        result = SymptomInterpreter(ai_service=MisreadContextualNoAiService()).interpret(
            "没有",
            existing,
        )

        self.assertEqual(result.case_summary, existing["case_summary"])
        self.assertEqual(result.duration, "半天多")
        self.assertEqual(result.used_medicines, "未使用")
        self.assertEqual(result.follow_up_question, "有没有药物过敏或明确不能使用的药？")
        self.assertEqual(result.assistant_reply, result.follow_up_question)
        self.assertFalse(any(item.evidence == "没有" for item in result.observations))


if __name__ == "__main__":
    unittest.main()
