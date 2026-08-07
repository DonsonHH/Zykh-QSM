from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.offline_inquiry_rules import OfflineInquiryRules, RULES  # noqa: E402
from app.services.ai_service import AiService  # noqa: E402


class FailingLocalClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("offline inquiry rules must not call the board model")

    def status(self):
        return {"ok": False, "ready": False}


class OfflineInquiryRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = OfflineInquiryRules()

    def test_heat_complaint_is_recorded_and_starts_symptom_followups(self) -> None:
        result = self.rules.extract(
            "我好像有点中暑头晕",
            {"conversation_turns": 1, "conversation": []},
            {"name": "张三"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "offline_rules")
        self.assertEqual(result["case_summary"], "暑热不适")
        self.assertEqual(result["next_action"], "ask")
        self.assertTrue(any(term in result["assistant_reply"] for term in ("恶心", "乏力", "出汗")))
        self.assertEqual(result["observations"][0]["evidence"], "我好像有点中暑头晕")

    def test_ai_service_local_mode_uses_rules_without_calling_board_model(self) -> None:
        client = FailingLocalClient()
        with patch(
            "app.services.ai_service.settings",
            SimpleNamespace(ai_mode="local", offline_inquiry_mode="rules"),
        ):
            result = AiService(local_client=client).extract_inquiry_information(
                "我中暑了",
                {"conversation_turns": 1, "conversation": []},
                {},
            )

        self.assertEqual(result["source"], "offline_rules")
        self.assertEqual(client.calls, 0)

    def test_contextual_answers_fill_record_then_request_vitals(self) -> None:
        existing = {
            "conversation_turns": 4,
            "case_summary": "暑热不适",
            "symptoms_text": "暑热不适",
            "duration": "刚开始",
            "used_medicines": "未使用",
            "observations": [{
                "concept": "暑热不适",
                "status": "present",
                "evidence": "我有点中暑",
                "source_turn": 1,
                "confidence": 0.9,
            }],
            "conversation": [{"role": "assistant", "content": "有没有药物过敏或明确不能使用的药？"}],
            "vitals": {},
        }

        result = self.rules.extract("这些都没有", existing, {"name": "张三"})

        self.assertEqual(result["allergy_or_contraindication"], "无")
        self.assertEqual(result["next_action"], "measure_vitals")
        self.assertNotIn("这些都没有", [item["concept"] for item in result["observations"]])

    def test_question_wording_varies_without_random_test_flakes(self) -> None:
        replies = {
            self.rules.extract(
                phrase,
                {"conversation_turns": index, "conversation": []},
                {},
            )["assistant_reply"]
            for index, phrase in enumerate(("我中暑了", "暴晒后头晕", "闷热后不舒服"), 1)
        }

        self.assertGreaterEqual(len(replies), 2)

    def test_heat_candidate_ranking_selects_only_existing_safe_candidate(self) -> None:
        result = self.rules.rank(
            {"case_summary": "暑热不适", "observations": []},
            [
                {"id": "slot-08-huoxiang-zhengqi", "dosage": "口服，一次1丸，一日2次。"},
                {"id": "slot-13-ibuprofen", "dosage": "资料待补录。"},
            ],
        )

        self.assertEqual(result["options"][0]["medicine_ids"], ["slot-08-huoxiang-zhengqi"])
        self.assertNotIn("slot-13-ibuprofen", result["options"][0]["medicine_ids"])

    def test_minor_wound_builds_primary_and_alternative_care_sequences(self) -> None:
        candidates = [
            {"id": medicine_id, "dosage": "按说明使用。"}
            for medicine_id in (
                "slot-17-iodophor",
                "slot-22-cotton-swab",
                "slot-20-bandage",
                "slot-10-gauze",
            )
        ]
        result = self.rules.rank(
            {"case_summary": "轻微外伤", "observations": []},
            candidates,
        )

        self.assertEqual(len(result["options"]), 2)
        self.assertEqual(result["options"][0]["medicine_ids"][0], "slot-17-iodophor")
        self.assertEqual(result["options"][1]["medicine_ids"][-1], "slot-10-gauze")

    def test_natural_repeated_negative_answer_does_not_repeat_allergy_question(self) -> None:
        existing = {
            "conversation_turns": 4,
            "case_summary": "暑热不适",
            "duration": "半小时",
            "used_medicines": "未使用",
            "conversation": [{"role": "assistant", "content": "有没有药物过敏或明确不能使用的药？"}],
            "vitals": {},
        }

        result = self.rules.extract("我说没有啊", existing, {"name": "李四"})

        self.assertEqual(result["allergy_or_contraindication"], "无")
        self.assertEqual(result["next_action"], "measure_vitals")

    def test_additional_common_complaints_map_to_cabinet_categories(self) -> None:
        cases = (
            ("我发烧而且全身酸痛", "发热不适", "slot-01-fufang-ganmaoling"),
            ("嘴里有口腔溃疡", "口腔不适", "slot-11-guilin-xiguashuang"),
            ("身上起疹子而且皮肤瘙痒", "皮肤过敏不适", "slot-23-desloratadine"),
        )
        candidates = [
            {"id": medicine_id, "dosage": "按说明核验。"}
            for medicine_id in (
                "slot-01-fufang-ganmaoling",
                "slot-13-ibuprofen",
                "slot-11-guilin-xiguashuang",
                "slot-07-yinhuang",
                "slot-23-desloratadine",
            )
        ]

        for transcript, case_summary, primary_id in cases:
            with self.subTest(transcript=transcript):
                extracted = self.rules.extract(transcript, {"conversation_turns": 1, "conversation": []}, {})
                ranked = self.rules.rank({"case_summary": case_summary, "observations": []}, candidates)
                self.assertEqual(extracted["case_summary"], case_summary)
                self.assertEqual(ranked["options"][0]["medicine_ids"], [primary_id])

    def test_recent_sore_throat_history_does_not_turn_into_a_cough_flow(self) -> None:
        result = self.rules.extract(
            "我嗓子有一点痛，但我没有咳嗽",
            {"conversation_turns": 1, "conversation": []},
            {},
        )

        self.assertEqual(result["case_summary"], "咽喉不适")
        self.assertNotIn("干咳", result["assistant_reply"])
        self.assertNotIn("有痰", result["assistant_reply"])

    def test_wound_bleeding_answer_is_not_stored_as_duration(self) -> None:
        existing = {
            "conversation_turns": 2,
            "case_summary": "轻微外伤",
            "observations": [{
                "concept": "轻微外伤",
                "status": "present",
                "evidence": "我膝盖擦伤了",
                "source_turn": 1,
                "confidence": 0.9,
            }],
            "conversation": [{
                "role": "assistant",
                "content": "现在有没有持续出血或明显肿痛？",
            }],
        }

        result = self.rules.extract("稍微出一点点血，不算多", existing, {})

        self.assertEqual(result["duration"], "")
        self.assertNotEqual(result["assistant_reply"], "现在有没有持续出血或明显肿痛？")

    def test_common_asr_aliases_are_normalized_for_safety_information(self) -> None:
        existing = {
            "conversation_turns": 6,
            "case_summary": "咽喉不适",
            "duration": "半天",
            "used_medicines": "未使用",
            "conversation": [{"role": "assistant", "content": "有没有药物过敏或明确不能使用的药？"}],
        }

        result = self.rules.extract("我头包过敏", existing, {})

        self.assertEqual(result["allergy_or_contraindication"], "头孢过敏或禁忌")

        complaint = self.rules.extract(
            "我胳膊有一些他声，有点痛",
            {"conversation_turns": 1, "conversation": []},
            {},
        )
        self.assertEqual(complaint["case_summary"], "轻微外伤")

    def test_rule_catalog_covers_common_spoken_complaints(self) -> None:
        cases = (
            ("喉咙疼但是不咳嗽", "咽喉不适"),
            ("一直干咳，晚上更厉害", "咳嗽咳痰不适"),
            ("鼻子痒还连续打喷嚏", "鼻部过敏不适"),
            ("吃完饭以后反酸烧心", "反酸烧心不适"),
            ("肚子胀还总是打嗝", "胃肠胀满"),
            ("想吐，还有一点干呕", "恶心呕吐不适"),
            ("嘴里长了两个溃疡", "口腔不适"),
            ("脚趾缝脱皮还很痒", "皮肤真菌样不适"),
            ("胳膊扭了一下，现在有点痛", "肌肉关节不适"),
            ("眼睛干涩像有沙子", "眼部干涩"),
            ("站起来眼前发黑，走路发飘", "头晕不适"),
            ("太阳穴一跳一跳地疼", "头痛不适"),
            ("浑身没劲，特别容易累", "乏力不适"),
            ("晚上总睡不着，还容易醒", "睡眠不适"),
            ("耳朵里面疼，还有闷堵感", "耳部不适"),
            ("小便时刺痛，总想上厕所", "泌尿不适"),
            ("手背被热水轻微烫红了", "轻微烫伤"),
        )

        for transcript, expected in cases:
            with self.subTest(transcript=transcript):
                result = self.rules.extract(
                    transcript,
                    {"conversation_turns": 1, "conversation": []},
                    {},
                )
                self.assertEqual(result["case_summary"], expected)
                self.assertEqual(result["next_action"], "ask")

    def test_every_rule_has_three_stages_of_symptom_questions(self) -> None:
        for rule in RULES:
            with self.subTest(rule=rule.key):
                questions = self.rules._detail_questions(rule)
                self.assertEqual(len(questions), 3)
                self.assertTrue(all(len(variants) >= 2 for variants in questions))

    def test_offline_questions_do_not_routinely_ask_about_standing_or_walking(self) -> None:
        banned = ("正常站立", "正常行走", "站立不稳", "走路不稳", "站不稳", "走路、")
        for rule in RULES:
            with self.subTest(rule=rule.key):
                questions = self.rules._detail_questions(rule)
                for question in (item for variants in questions for item in variants):
                    self.assertFalse(
                        any(term in question for term in banned),
                        f"{rule.key} still contains a routine mobility question: {question}",
                    )

    def test_heat_inquiry_collects_three_symptom_details_then_summarizes(self) -> None:
        existing = {"conversation_turns": 1, "conversation": [], "vitals": {}}
        turns = (
            ("我好像有点中暑头晕", ("恶心", "乏力", "出汗")),
            ("有一点恶心，也出了很多汗", ("暴晒", "闷热", "活动")),
            ("刚才在太阳下走了很久", ("休息", "通风", "补水")),
            ("喝水休息以后好了一点", ("目前主要是暑热不适", "持续", "多久")),
            ("半个小时", ("用过药", "吃过", "用药")),
            ("还没有用过药", ("过敏", "禁忌", "不能用")),
            ("我说没有啊", ("体征", "额温", "血氧")),
        )

        for transcript, expected_reply_terms in turns:
            result = self.rules.extract(transcript, existing, {"name": "张三"})
            self.assertTrue(any(term in result["assistant_reply"] for term in expected_reply_terms))
            existing.update({
                "conversation_turns": existing["conversation_turns"] + 1,
                "case_summary": result["case_summary"],
                "duration": result["duration"],
                "used_medicines": result["used_medicines"],
                "allergy_or_contraindication": result["allergy_or_contraindication"],
                "observations": result["observations"],
            })
            existing["conversation"] = [
                *existing["conversation"],
                {"role": "user", "content": transcript},
                {"role": "assistant", "content": result["assistant_reply"]},
            ]

        self.assertEqual(result["used_medicines"], "未使用")
        self.assertEqual(result["allergy_or_contraindication"], "无")
        self.assertEqual(result["next_action"], "measure_vitals")
        detail_observations = [
            item for item in result["observations"]
            if item["concept"].startswith("暑热不适·补充")
        ]
        self.assertEqual(len(detail_observations), 3)
        self.assertEqual(result["case_summary"], "暑热不适")


if __name__ == "__main__":
    unittest.main()
