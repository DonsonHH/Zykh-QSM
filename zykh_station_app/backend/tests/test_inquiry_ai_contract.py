from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ai_service import AiService  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402


class FakeLocalClient:
    def __init__(self, reply: dict):
        self.reply = reply
        self.last_messages = []
        self.last_kwargs = {}

    def chat(self, messages, **kwargs):
        self.last_messages = messages
        self.last_kwargs = kwargs
        return self.reply


class InquiryAiContractTest(unittest.TestCase):
    @patch("app.services.ai_service.settings")
    def test_local_model_uses_open_case_schema_instead_of_classification_codes(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": (
                    '{"s":"起身时眼前发黑","f":[["体位变化相关不适","present",'
                    '"起身时眼前发黑",2,0.9]],"u":["是否心悸"],'
                    '"n":"measure_vitals","q":"","r":"需要结合体征","k":"medium","c":0.9}'
                ),
            }
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "起身时眼前发黑",
            {"conversation_turns": 2, "conversation": []},
            {"age": 65},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["observations"][0]["concept"], "体位变化相关不适")
        self.assertEqual(result["next_action"], "measure_vitals")
        self.assertNotIn("分类码", client.last_messages[0]["content"])
        self.assertNotIn("allowed_dimensions", client.last_messages[1]["content"])

    def test_safe_pool_excludes_prescription_expired_and_allergy_conflicts(self) -> None:
        pool = MedicineKnowledgeRepository().safe_candidate_pool("青霉素过敏")
        ids = {medicine.id for medicine in pool}

        self.assertNotIn("slot-04-amoxicillin", ids)
        self.assertNotIn("slot-14-oseltamivir", ids)
        self.assertNotIn("slot-21-amlodipine", ids)
        self.assertTrue(ids)

    def test_ai_selection_is_limited_to_the_safe_pool_and_two_options(self) -> None:
        knowledge = MedicineKnowledgeRepository()
        pool = knowledge.safe_candidate_pool("头孢过敏")
        options = knowledge.options_from_ai_selection(
            {
                "options": [
                    {
                        "option_id": "primary",
                        "label": "主方案",
                        "reason": "更贴近当前的暑湿和胃肠不适。",
                        "medicine_ids": ["slot-08-huoxiang-zhengqi", "slot-04-amoxicillin"],
                    },
                    {
                        "option_id": "alternative",
                        "label": "备选",
                        "reason": "如果主要表现为胃部不适，可对照这一选择。",
                        "medicine_ids": ["slot-12-hydrotalcite"],
                    },
                    {
                        "option_id": "ignored",
                        "label": "多余方案",
                        "medicine_ids": ["slot-06-lactulose"],
                    },
                ]
            },
            pool,
        )

        self.assertEqual(len(options), 2)
        selected_ids = {medicine.id for option in options for medicine in option.medicines}
        self.assertNotIn("slot-04-amoxicillin", selected_ids)
        self.assertEqual(options[0].label, "主方案")


if __name__ == "__main__":
    unittest.main()
