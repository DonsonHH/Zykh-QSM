from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import InquiryExtractedInformation, InquiryObservation  # noqa: E402
from app.services.inquiry_dialogue_policy import (  # noqa: E402
    explicit_topic_evidence,
    final_question_clause,
    focused_followup_question,
    independent_question_slot_count,
    medication_question_window,
    minimum_clinical_information_ready,
    plain_language_question,
    symptom_scope_confirmation_question,
    symptom_scope_explicitly_complete,
)


def extracted(**overrides) -> InquiryExtractedInformation:
    values = {
        "case_summary": "用户描述头痛。",
        "symptoms_text": "头痛",
        "duration": "今天早上开始",
        "observations": [
            InquiryObservation(
                concept="头痛",
                status="present",
                evidence="我头有点痛",
                source_turn=1,
                confidence=0.9,
            )
        ],
    }
    values.update(overrides)
    return InquiryExtractedInformation(**values)


class InquiryDialoguePolicyTest(unittest.TestCase):
    def test_multi_slot_model_question_is_replaced_with_one_answer_slot(self) -> None:
        state = extracted()
        question, topic = focused_followup_question(
            state,
            "头痛持续多久，是持续性还是阵发性，有没有发热或恶心？",
            "headache_onset",
        )

        self.assertEqual(topic, "headache_onset")
        self.assertEqual(independent_question_slot_count(question), 1)
        self.assertNotIn("有没有发热", question)

    def test_two_clinical_topics_joined_by_or_are_not_one_answer_slot(self) -> None:
        state = extracted()
        question, topic = focused_followup_question(
            state,
            "现在有没有发热或呼吸费力？",
            "fever",
        )

        self.assertEqual(topic, "fever")
        self.assertEqual(question, "你现在量到的体温是多少度？如果还没量，直接说还没量就可以。")
        self.assertNotIn("呼吸", question)

    def test_professional_headache_wording_is_rewritten_for_families(self) -> None:
        state = extracted()
        question, topic = focused_followup_question(
            state,
            "这次头痛有没有伴随异常神经表现，比如单侧无力？",
            "headache_red_flags",
        )

        self.assertEqual(topic, "headache_red_flags")
        self.assertEqual(question, "头痛时，有没有一边手脚突然使不上力？")
        self.assertNotIn("神经", question)
        self.assertNotIn("单侧", question)

    def test_plain_language_safety_net_rewrites_common_medical_terms(self) -> None:
        self.assertEqual(
            plain_language_question("有没有视物异常？"),
            "有没有看东西突然模糊或重影？",
        )

    def test_bundled_symptom_list_is_not_treated_as_one_precise_question(self) -> None:
        self.assertGreater(
            independent_question_slot_count("有没有发热、咳嗽、咽痛、鼻塞、全身酸痛？"),
            1,
        )

    def test_only_final_question_clause_is_validated(self) -> None:
        self.assertEqual(
            final_question_clause("我记下了咽痛和流鼻涕。这些症状持续多久了？"),
            "这些症状持续多久了？",
        )

    def test_explicit_negative_breathing_fact_prevents_repeat(self) -> None:
        self.assertEqual(
            explicit_topic_evidence("昨晚开始咳嗽，但没有胸闷气短")["breathing"],
            "昨晚开始咳嗽，但没有胸闷气短",
        )

    def test_valid_single_choice_question_is_kept(self) -> None:
        state = extracted(symptoms_text="头晕", case_summary="用户描述头晕。")
        question, topic = focused_followup_question(
            state,
            "头晕更像周围在转，还是眼前发黑？",
            "symptom_detail",
        )

        self.assertEqual(topic, "symptom_detail")
        self.assertEqual(question, "头晕更像周围在转，还是眼前发黑？")
        self.assertEqual(independent_question_slot_count(question), 1)

    def test_routine_standing_or_walking_question_is_never_shown(self) -> None:
        state = extracted(symptoms_text="中暑头晕", case_summary="用户描述晒后头晕。")
        question, topic = focused_followup_question(
            state,
            "现在还能正常站立和行走吗？",
            "severity",
        )

        self.assertEqual(topic, "severity")
        self.assertEqual(question, "现在最难受的感觉是轻微、明显，还是很严重？")
        self.assertNotIn("站立", question)
        self.assertNotIn("行走", question)

    def test_dizziness_detail_fallback_avoids_mobility_question(self) -> None:
        state = extracted(symptoms_text="头晕", case_summary="用户描述头晕。")
        question, topic = focused_followup_question(
            state,
            "头晕时会不会站不稳？",
            "symptom_detail",
        )

        self.assertEqual(topic, "symptom_detail")
        self.assertEqual(question, "头晕时更像周围在转，还是眼前发黑？")
        self.assertNotIn("站", question)

    def test_answered_topic_is_not_repeated(self) -> None:
        state = extracted(
            clarification_answers={"onset": "今天早上开始"},
            asked_clarifications=["onset"],
            pending_clarification="onset",
        )
        question, topic = focused_followup_question(
            state,
            "这种不舒服是从什么时候开始的？",
            "onset",
        )

        self.assertNotEqual(topic, "onset")
        self.assertNotIn("什么时候开始", question)

    def test_headache_requires_real_safety_topics_before_ready(self) -> None:
        state = extracted(
            clarification_answers={
                "main_symptom": "头痛",
                "onset": "今天早上开始",
                "headache_onset": "逐渐出现",
                "headache_red_flags": "没有说话含糊、单侧无力或视物异常",
                "fever": "还没量体温",
            }
        )
        self.assertTrue(minimum_clinical_information_ready(state))

    def test_medication_window_matches_onset(self) -> None:
        self.assertEqual(
            medication_question_window("刚才开始"),
            "从刚才这次不舒服开始到现在",
        )
        self.assertEqual(
            medication_question_window("今天早上开始"),
            "从今天早上这次不舒服开始到现在",
        )

    def test_symptom_scope_question_is_one_natural_answer_slot(self) -> None:
        question = symptom_scope_confirmation_question(
            extracted(symptoms_text="咽喉疼痛、头痛")
        )
        self.assertIn("咽喉疼痛、头痛", question)
        self.assertIn("其他明显不舒服", question)
        self.assertEqual(independent_question_slot_count(question), 1)

    def test_colloquial_scope_completion_is_recognized(self) -> None:
        self.assertTrue(symptom_scope_explicitly_complete("就这些，别的没有了"))
        self.assertFalse(symptom_scope_explicitly_complete("还有一点发冷"))

    def test_scope_question_deduplicates_display_only_symptom_aliases(self) -> None:
        question = symptom_scope_confirmation_question(
            extracted(symptoms_text="咽痛、头痛、声音沙哑、咽喉疼痛")
        )
        self.assertIn("咽痛、头痛、声音沙哑", question)
        self.assertNotIn("咽喉疼痛", question)


if __name__ == "__main__":
    unittest.main()
