from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.offline_inquiry_rules import OfflineInquiryRules  # noqa: E402
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

    def test_heat_complaint_is_recorded_and_asks_one_question(self) -> None:
        result = self.rules.extract(
            "我好像有点中暑头晕",
            {"conversation_turns": 1, "conversation": []},
            {"name": "张三"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "offline_rules")
        self.assertEqual(result["case_summary"], "暑热不适")
        self.assertEqual(result["next_action"], "ask")
        self.assertTrue(any(term in result["assistant_reply"] for term in ("多久", "什么时候", "多长时间")))
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
                {"id": "slot-03-ganmao-qingre", "dosage": "开水冲服。"},
            ],
        )

        self.assertEqual(result["options"][0]["medicine_ids"], ["slot-08-huoxiang-zhengqi"])
        self.assertNotIn("slot-03-ganmao-qingre", result["options"][0]["medicine_ids"])

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
            ("我发烧头痛", "发热头痛不适", "slot-01-fufang-ganmaoling"),
            ("嘴里有口腔溃疡", "口腔咽喉不适", "slot-11-guilin-xiguashuang"),
            ("身上起疹子而且皮肤瘙痒", "皮肤过敏不适", "slot-23-desloratadine"),
        )
        candidates = [
            {"id": medicine_id, "dosage": "按说明核验。"}
            for medicine_id in (
                "slot-01-fufang-ganmaoling",
                "slot-03-ganmao-qingre",
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

    def test_heat_inquiry_collects_one_field_per_turn_in_expected_order(self) -> None:
        existing = {"conversation_turns": 1, "conversation": [], "vitals": {}}
        turns = (
            ("我好像有点中暑头晕", ("持续", "什么时候", "多长时间")),
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


if __name__ == "__main__":
    unittest.main()
