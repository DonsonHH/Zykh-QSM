from __future__ import annotations

import json
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


class FakeHttpResponse:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class InquiryAiContractTest(unittest.TestCase):
    @patch("app.services.ai_service.AiService._network_local_mode", return_value=False)
    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_cloud_inquiry_retries_once_after_a_transient_timeout(
        self,
        mocked_settings,
        mocked_urlopen,
        _mocked_local_mode,
    ) -> None:
        mocked_settings.ai_mode = "cloud"
        mocked_settings.ai_api_key = "test-key"
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        mocked_settings.ai_api_base = "https://api.deepseek.com/chat/completions"
        mocked_settings.ai_model = "deepseek-v4-flash"
        mocked_settings.ai_inquiry_timeout_seconds = 45
        mocked_settings.ai_inquiry_attempt_timeout_seconds = 12
        mocked_settings.ai_inquiry_max_attempts = 2
        mocked_settings.ai_inquiry_retry_delay_seconds = 0
        mocked_urlopen.side_effect = [
            TimeoutError("read timed out"),
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "case_summary": "头晕、流清鼻涕持续半天。",
                                        "observations": [],
                                        "next_action": "ask",
                                        "assistant_reply": "请问有没有发热或呼吸不适？",
                                        "risk_level": "low",
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        }
                    ]
                }
            ),
        ]
        local_client = FakeLocalClient({"ok": False, "error_message": "local unavailable"})

        result = AiService(local_client=local_client).extract_inquiry_information(
            "大概半天左右",
            {"conversation_turns": 2, "conversation": []},
            {"name": "张三", "age": 65},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cloud")
        self.assertEqual(result["next_action"], "ask")
        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(local_client.last_messages, [])

    @patch("app.services.ai_service.AiService._network_local_mode", return_value=False)
    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_cloud_inquiry_retries_once_after_an_invalid_json_completion(
        self,
        mocked_settings,
        mocked_urlopen,
        _mocked_local_mode,
    ) -> None:
        mocked_settings.ai_mode = "cloud"
        mocked_settings.ai_api_key = "test-key"
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        mocked_settings.ai_api_base = "https://api.deepseek.com/chat/completions"
        mocked_settings.ai_model = "deepseek-v4-flash"
        mocked_settings.ai_inquiry_timeout_seconds = 45
        mocked_settings.ai_inquiry_attempt_timeout_seconds = 12
        mocked_settings.ai_inquiry_max_attempts = 2
        mocked_settings.ai_inquiry_retry_delay_seconds = 0
        mocked_urlopen.side_effect = [
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": '{"case_summary":"头晕'},
                        }
                    ]
                }
            ),
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": (
                                    "<think>忽略这里</think>\n```json\n"
                                    '{"case_summary":"头晕半天","observations":[],'
                                    '"next_action":"measure_vitals",'
                                    '"assistant_reply":"需要测量额温、心率和血氧。",'
                                    '"risk_level":"medium"}\n```'
                                )
                            },
                        }
                    ]
                }
            ),
        ]

        result = AiService(
            local_client=FakeLocalClient({"ok": False, "error_message": "local unavailable"})
        ).extract_inquiry_information(
            "头晕半天",
            {"conversation_turns": 1, "conversation": []},
            {"name": "张三", "age": 65},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["next_action"], "measure_vitals")
        self.assertEqual(mocked_urlopen.call_count, 2)

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
                        "usage_by_medicine": {
                            "slot-08-huoxiang-zhengqi": "口服，一次1丸，一日2次。",
                        },
                    },
                    {
                        "option_id": "alternative",
                        "label": "备选",
                        "reason": "如果主要表现为胃部不适，可对照这一选择。",
                        "medicine_ids": ["slot-12-hydrotalcite"],
                        "usage_by_medicine": {
                            "slot-12-hydrotalcite": "一次3片，一日4次。",
                        },
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
        self.assertEqual(options[0].medicines[0].recommended_usage, "口服，一次1丸，一日2次")
        self.assertEqual(
            options[1].medicines[0].recommended_usage,
            options[1].medicines[0].dosage,
        )

    @patch("app.services.ai_service.settings")
    def test_candidate_ranking_prompt_treats_first_aid_supplies_as_valid_options(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": json.dumps(
                    {
                        "summary": "浅表伤口已经止血。",
                        "options": [
                            {
                                "option_id": "primary",
                                "label": "清洁与覆盖",
                                "reason": "可先清洁伤口并覆盖保护。",
                                "medicine_ids": ["slot-17-iodophor", "slot-10-gauze"],
                                "usage_by_medicine": {
                                    "slot-17-iodophor": "先用碘伏消毒液清洁伤口",
                                    "slot-10-gauze": "最后用医用纱布覆盖保护",
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "手部浅表刀伤，已经止血，无感染迹象。",
                "risk_level": "low",
                "used_medicines": "未使用",
                "allergy_or_contraindication": "无",
            },
            [
                {
                    "id": "slot-17-iodophor",
                    "name": "碘伏消毒液",
                    "category": "外伤护理",
                    "indications": "用于浅表创面清洁与消毒。",
                },
                {
                    "id": "slot-10-gauze",
                    "name": "医用纱布敷料",
                    "category": "外伤护理",
                    "indications": "用于清洁后的浅表伤口覆盖。",
                },
            ],
        )

        self.assertTrue(result["ok"])
        self.assertIn("外伤护理用品", client.last_messages[0]["content"])
        self.assertIn("不应仅因不需要口服药", client.last_messages[0]["content"])
        self.assertIn("同样符合当前情况的第二种安全选择", client.last_messages[0]["content"])
        self.assertIn("usage_by_medicine", client.last_messages[0]["content"])
        self.assertEqual(result["options"][0]["medicine_ids"], ["slot-17-iodophor", "slot-10-gauze"])


if __name__ == "__main__":
    unittest.main()
