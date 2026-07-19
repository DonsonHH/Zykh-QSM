from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.symptom_interpreter import SymptomInterpreter  # noqa: E402


class FakeAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "cloud",
            "symptom_dimensions": ["感冒鼻部症状"],
            "dimension_evidence": {"感冒鼻部症状": "鼻塞"},
            "duration": "三天",
            "used_medicines": "已使用",
            "allergy_or_contraindication": "阿司匹林过敏",
            "follow_up_question": "这种不舒服持续多久了？",
            "reasoning_summary": "用户明确提到鼻塞。",
            "action_intent": "measure_vitals",
            "action_reason": "体征会影响后续安全核验",
            "confidence": 0.91,
        }


class UnavailableAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {"ok": False}


class NegatedEvidenceAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "cloud",
            "symptom_dimensions": ["过敏瘙痒"],
            "dimension_evidence": {"过敏瘙痒": "没有过敏"},
            "allergy_or_contraindication": "没有过敏",
            "confidence": 0.9,
        }


class FollowupOnlyAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "local_llm",
            "follow_up_question": "这种头晕是突然出现的，还是慢慢加重的？",
            "action_intent": "ask",
            "reasoning_summary": "我听到你主要是头晕。",
        }


class SparseLocalAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {"ok": True, "source": "local_llm", "action_intent": "ask"}


class ContextAwareAiService:
    def extract_inquiry_information(self, *_args, **_kwargs):
        return {
            "ok": True,
            "source": "cloud",
            "symptom_dimensions": ["感冒鼻部症状"],
            "dimension_evidence": {"感冒鼻部症状": "鼻塞"},
            "follow_up_question": "头晕是在起身时更明显，还是一直都有？",
            "assistant_reply": "鼻塞我记下了。头晕是在起身时更明显，还是一直都有？",
            "action_intent": "ask",
            "confidence": 0.86,
        }


class SymptomInterpreterTest(unittest.TestCase):
    def test_model_cannot_invent_scalar_facts_not_present_in_transcript(self) -> None:
        result = SymptomInterpreter(ai_service=FakeAiService()).interpret("刚有点鼻塞")

        self.assertEqual(result.symptom_dimensions, ["感冒鼻部症状"])
        self.assertEqual(result.dimension_evidence, {"感冒鼻部症状": "鼻塞"})
        self.assertEqual(result.duration, "")
        self.assertEqual(result.used_medicines, "")
        self.assertEqual(result.allergy_or_contraindication, "")
        self.assertEqual(result.action_intent, "measure_vitals")
        self.assertEqual(result.reasoning_summary, "用户明确提到鼻塞。")

    def test_negated_symptoms_are_not_added_as_dimensions(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret("没有过敏，也没有头痛")

        self.assertEqual(result.symptom_dimensions, [])

    def test_standalone_negation_does_not_add_a_positive_feature(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret("有点怕冷，但是不口渴")

        self.assertIn("明显畏寒", result.symptom_features)
        self.assertNotIn("明显口渴", result.symptom_features)

    def test_head_discomfort_is_understood_without_asking_for_body_location(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret("头有点不舒服")

        self.assertIn("发热全身不适", result.symptom_dimensions)
        self.assertEqual(result.dimension_evidence["发热全身不适"], "头有点不舒服")

    def test_drug_allergy_is_not_misread_as_active_skin_or_nasal_symptom(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret("我对头孢过敏")

        self.assertNotIn("过敏瘙痒", result.symptom_dimensions)
        self.assertNotIn("鼻炎过敏", result.symptom_dimensions)
        self.assertEqual(result.allergy_or_contraindication, "头孢过敏")

    def test_allergy_is_extracted_from_a_longer_spoken_sentence(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret(
            "我有点头晕，已经半天了，还没有用药，我对头孢过敏"
        )

        self.assertEqual(result.allergy_or_contraindication, "头孢过敏")

    def test_model_dimension_with_negated_evidence_is_rejected(self) -> None:
        result = SymptomInterpreter(ai_service=NegatedEvidenceAiService()).interpret("没有过敏")

        self.assertEqual(result.symptom_dimensions, [])
        self.assertEqual(result.allergy_or_contraindication, "无")

    def test_negated_used_medicine_phrase_is_not_misread_as_used(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret("还没用过药")

        self.assertEqual(result.used_medicines, "未使用")

    def test_natural_short_duration_is_extracted(self) -> None:
        for transcript in ("五分钟", "十秒钟", "没多久", "两年半", "一天半", "去年"):
            with self.subTest(transcript=transcript):
                result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret(transcript)
                self.assertEqual(result.duration, transcript)

    def test_uncertain_allergy_history_is_not_recorded_as_a_positive_allergy(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret("没有药物过敏或不能明确")

        self.assertEqual(result.allergy_or_contraindication, "不确定")

    def test_clear_runny_nose_phrase_is_kept_as_nasal_cold_evidence(self) -> None:
        result = SymptomInterpreter(ai_service=UnavailableAiService()).interpret("今天开始流清鼻涕，还有一点头痛")

        self.assertIn("感冒鼻部症状", result.symptom_dimensions)
        self.assertEqual(result.dimension_evidence["感冒鼻部症状"], "流清鼻涕")

    def test_model_followup_is_kept_even_when_the_turn_adds_no_new_structured_field(self) -> None:
        result = SymptomInterpreter(ai_service=FollowupOnlyAiService()).interpret(
            "就是刚才说的那种感觉",
            {"symptom_dimensions": ["恶心暑湿"], "current_stage": "clarification"},
        )

        self.assertEqual(result.source, "local_llm")
        self.assertEqual(result.follow_up_question, "这种头晕是突然出现的，还是慢慢加重的？")

    def test_sparse_local_model_result_keeps_local_dialogue_path_and_verified_facts(self) -> None:
        result = SymptomInterpreter(ai_service=SparseLocalAiService()).interpret(
            "我中暑头晕半天了，还没有用药，对头孢过敏",
            {"current_stage": "symptoms"},
        )

        self.assertEqual(result.source, "local_llm")
        self.assertIn("恶心暑湿", result.symptom_dimensions)
        self.assertEqual(result.duration, "半天")
        self.assertEqual(result.used_medicines, "未使用")
        self.assertEqual(result.allergy_or_contraindication, "头孢过敏")

    def test_cloud_model_leads_ambiguous_symptom_interpretation_without_keyword_union(self) -> None:
        result = SymptomInterpreter(ai_service=ContextAwareAiService()).interpret("我鼻塞，还有一点头晕")

        self.assertEqual(result.symptom_dimensions, ["感冒鼻部症状"])
        self.assertEqual(result.follow_up_question, "头晕是在起身时更明显，还是一直都有？")
        self.assertEqual(result.assistant_reply, "鼻塞我记下了。头晕是在起身时更明显，还是一直都有？")


if __name__ == "__main__":
    unittest.main()
