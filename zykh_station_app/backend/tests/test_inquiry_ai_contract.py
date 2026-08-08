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
    def __init__(self, reply: dict | list[dict]):
        self.reply = reply
        self.last_messages = []
        self.last_kwargs = {}
        self.messages_history = []
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.last_messages = messages
        self.last_kwargs = kwargs
        self.messages_history.append(messages)
        index = self.calls
        self.calls += 1
        if isinstance(self.reply, list):
            return self.reply[min(index, len(self.reply) - 1)]
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


class FakeWeatherContext:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def inquiry_context(self, transcript, existing):
        self.calls.append((transcript, existing))
        return self.value


def local_ranking_reply(options: list[dict], summary: str = "需要结合当前信息继续观察。") -> dict:
    return {
        "ok": True,
        "reply": json.dumps(
            {
                "assessment": {
                    "summary": summary,
                    "possible_conditions": [],
                    "next_steps": ["继续记录症状变化"],
                    "seek_care_if": ["症状明显加重时及时联系医生"],
                },
                "options": options,
            },
            ensure_ascii=False,
        ),
    }


class InquiryAiContractTest(unittest.TestCase):
    @patch("app.services.ai_service.AiService._cloud_reachable", return_value=True)
    @patch("app.services.ai_service.db.get_setting", return_value="local")
    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_local_display_mode_does_not_change_cloud_inquiry(
        self,
        mocked_settings,
        mocked_urlopen,
        mocked_display_mode,
        _mocked_cloud_probe,
    ) -> None:
        mocked_settings.ai_mode = "auto"
        mocked_settings.ai_cloud_in_local_display = True
        mocked_settings.ai_api_key = "test-key"
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        mocked_settings.ai_api_base = "https://api.deepseek.com/chat/completions"
        mocked_settings.ai_model = "deepseek-v4-flash"
        mocked_settings.ai_inquiry_timeout_seconds = 45
        mocked_settings.ai_inquiry_attempt_timeout_seconds = 12
        mocked_settings.ai_inquiry_max_attempts = 1
        mocked_settings.ai_inquiry_retry_delay_seconds = 0
        mocked_settings.inquiry_location_name = "成都"
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "case_summary": "暑热环境后头晕。",
                                    "observations": [],
                                    "next_action": "measure_vitals",
                                    "assistant_reply": "先测量额温、心率和血氧。",
                                    "risk_level": "medium",
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ]
            }
        )
        local_client = FakeLocalClient({"ok": False, "error_message": "must not be called"})

        result = AiService(
            local_client=local_client,
            weather_context=FakeWeatherContext(None),
        ).extract_inquiry_information(
            "在外面晒过以后有点头晕",
            {"conversation_turns": 1, "conversation": []},
            {"name": "张三"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cloud")
        self.assertEqual(local_client.calls, 0)
        mocked_urlopen.assert_called_once()
        mocked_display_mode.assert_not_called()

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_cloud_inquiry_includes_chengdu_weather_as_non_diagnostic_context(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        mocked_settings.ai_mode = "cloud"
        mocked_settings.ai_api_key = "test-key"
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        mocked_settings.ai_api_base = "https://api.deepseek.com/chat/completions"
        mocked_settings.ai_model = "deepseek-v4-flash"
        mocked_settings.ai_inquiry_timeout_seconds = 45
        mocked_settings.ai_inquiry_attempt_timeout_seconds = 12
        mocked_settings.ai_inquiry_max_attempts = 1
        mocked_settings.ai_inquiry_retry_delay_seconds = 0
        mocked_settings.inquiry_location_name = "成都"
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "case_summary": "暴晒后头晕。",
                                    "observations": [],
                                    "next_action": "measure_vitals",
                                    "assistant_reply": "先测量额温、心率和血氧。",
                                    "risk_level": "medium",
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ]
            }
        )
        weather = FakeWeatherContext(
            {
                "location": "成都",
                "temperature_c": 34.2,
                "apparent_temperature_c": 38.7,
                "usage_note": "仅作为环境背景，不可单独用于判断病因。",
            }
        )

        result = AiService(
            local_client=FakeLocalClient({"ok": False}),
            weather_context=weather,
        ).extract_inquiry_information(
            "在外面晒了以后像是中暑，有点头晕",
            {"conversation_turns": 1, "conversation": []},
            {"name": "张三"},
        )

        self.assertTrue(result["ok"])
        request_payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(
            json.loads(request_payload["messages"][1]["content"])["environment_context"]["location"],
            "成都",
        )
        self.assertIn("不能仅凭天气认定中暑", request_payload["messages"][0]["content"])
        self.assertEqual(len(weather.calls), 1)

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_cloud_inquiry_retries_once_after_a_transient_timeout(
        self,
        mocked_settings,
        mocked_urlopen,
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

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_cloud_inquiry_retries_once_after_an_invalid_json_completion(
        self,
        mocked_settings,
        mocked_urlopen,
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

    @patch("app.services.ai_service.settings")
    def test_local_inquiry_accepts_full_schema_for_short_heatstroke_utterance(
        self,
        mocked_settings,
    ) -> None:
        """A valid full-field response must not fall into the generic retry message."""
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": json.dumps(
                    {
                        "case_summary": "中暑",
                        "observations": [
                            {
                                "concept": "中暑",
                                "status": "present",
                                "evidence": "我好像有点中暑",
                                "source_turn": 1,
                                "confidence": 0.9,
                            }
                        ],
                        "next_action": "ask",
                        "next_question": "这种不舒服大概持续多久了？",
                        "assistant_reply": "这种不舒服大概持续多久了？",
                        "risk_level": "low",
                        "risk_signals": [],
                    },
                    ensure_ascii=False,
                ),
            }
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "我好像有点中暑",
            {
                "conversation_turns": 1,
                "case_summary": "",
                "observations": [],
                "conversation": [],
            },
            {"name": "李四", "age": 72},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(result["case_summary"], "中暑")
        self.assertEqual(result["next_action"], "ask")
        self.assertNotIn("换一种说法", result.get("message", ""))

    @patch("app.services.ai_service.settings")
    def test_local_inquiry_preserves_explicit_complaint_when_model_returns_plain_text(
        self,
        mocked_settings,
    ) -> None:
        """A format miss must not erase a clear user utterance."""
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient({"ok": True, "reply": "中暑"})

        result = AiService(local_client=client).extract_inquiry_information(
            "我好像有点中暑",
            {"conversation_turns": 1, "conversation": []},
            {"name": "李四", "age": 72},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(result["case_summary"], "中暑")

    def test_safe_pool_excludes_prescription_expired_and_allergy_conflicts(self) -> None:
        pool = MedicineKnowledgeRepository().safe_candidate_pool("青霉素过敏")
        ids = {medicine.id for medicine in pool}

        self.assertNotIn("slot-04-amoxicillin", ids)
        self.assertNotIn("slot-14-oseltamivir", ids)
        self.assertNotIn("slot-21-amlodipine", ids)
        self.assertTrue(ids)

    def test_ai_selection_rejects_a_whole_option_when_any_id_is_outside_the_safe_pool(self) -> None:
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

        self.assertEqual(len(options), 1)
        selected_ids = {medicine.id for option in options for medicine in option.medicines}
        self.assertNotIn("slot-04-amoxicillin", selected_ids)
        self.assertNotIn("slot-08-huoxiang-zhengqi", selected_ids)
        self.assertEqual(options[0].label, "备选")
        self.assertEqual(options[0].medicines[0].id, "slot-12-hydrotalcite")
        self.assertEqual(
            options[0].medicines[0].recommended_usage,
            options[0].medicines[0].dosage,
        )

    @patch("app.services.ai_service.settings")
    def test_candidate_ranking_prompt_treats_first_aid_supplies_as_valid_options(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            local_ranking_reply(
                [
                    {
                        "option_id": "primary",
                        "label": "主方案",
                        "reason": "这组护理用品更贴近浅表伤口的清洁和覆盖。",
                        "medicine_ids": ["slot-17-iodophor", "slot-10-gauze"],
                        "usage_by_medicine": {},
                    }
                ],
                "手部浅表伤口需要先清洁并覆盖保护。",
            )
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "手部浅表刀伤，已经止血，无感染迹象。",
                "observations": [
                    {
                        "concept": "浅表刀伤",
                        "status": "present",
                        "evidence": "手部刀伤不深",
                    }
                ],
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
        self.assertEqual(result["source"], "local_llm")
        self.assertTrue(client.last_messages)
        self.assertTrue(result["options"])
        self.assertIn(
            result["options"][0]["medicine_ids"][0],
            {"slot-17-iodophor", "slot-10-gauze"},
        )
        self.assertIn("浅表伤口", result["options"][0]["reason"])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_does_not_recommend_when_model_returns_empty(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            local_ranking_reply([], "目前还不能确认具体不适。")
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "我有点吃饱了没事干",
                "observations": [
                    {
                        "concept": "我有点吃饱了没事干",
                        "status": "present",
                        "evidence": "我有点吃饱了没事干",
                    }
                ],
                "risk_level": "low",
                "used_medicines": "未使用",
                "allergy_or_contraindication": "无",
            },
            [
                {
                    "id": "slot-12-aluminium-magnesia",
                    "name": "铝碳酸镁咀嚼片",
                    "category": "胃部不适",
                    "indications": "用于胃酸、胃部不适。",
                    "dosage": "按说明书使用。",
                },
                {
                    "id": "slot-22-cotton-swab",
                    "name": "医用棉签",
                    "category": "外伤护理",
                    "indications": "用于外伤护理。",
                    "dosage": "按需使用。",
                },
            ],
        )

        self.assertTrue(client.last_messages)
        self.assertTrue(result["ok"])
        self.assertEqual(result["options"], [])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_rejects_a_truncated_business_contract(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": '{"options":[{"label":"主方案","reason":"先清洁再覆盖保护",'
                '"medicine_keys":["17","20"]',
            }
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "手部浅表擦伤",
                "observations": [{"concept": "擦伤", "status": "present", "evidence": "手部擦伤"}],
                "risk_level": "low",
            },
            [
                {
                    "id": "slot-17-iodophor",
                    "slot": "17",
                    "name": "碘伏消毒液",
                    "indications": "用于浅表创面清洁与消毒。",
                },
                {
                    "id": "slot-20-bandage",
                    "slot": "20",
                    "name": "创口贴",
                    "indications": "用于清洁后的浅表伤口覆盖。",
                },
            ],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["options"], [])
        self.assertEqual(client.last_kwargs["max_tokens"], 320)

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_rejects_the_legacy_line_format(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            {"ok": True, "reply": "A=17,20|先消毒再覆盖;B=10|覆盖并吸收渗液"}
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {"case_summary": "手部浅表擦伤", "risk_level": "low"},
            [
                {"id": "iodophor", "slot": "17", "name": "碘伏消毒液", "category": "外伤护理"},
                {"id": "bandage", "slot": "20", "name": "创口贴", "category": "外伤护理"},
                {"id": "gauze", "slot": "10", "name": "医用纱布敷料", "category": "外伤护理"},
            ],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["options"], [])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_keeps_four_items_in_a_care_sequence(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            local_ranking_reply(
                [
                    {
                        "option_id": "primary",
                        "label": "主方案",
                        "reason": "按顺序处理",
                        "medicine_ids": [
                            "medicine-17",
                            "medicine-22",
                            "medicine-20",
                            "medicine-19",
                        ],
                    }
                ]
            )
        )
        candidates = [
            {"id": f"medicine-{slot}", "slot": str(slot), "name": f"用品{slot}", "category": "外伤护理"}
            for slot in (17, 22, 20, 19)
        ]

        result = AiService(local_client=client).rank_inquiry_candidates(
            {"case_summary": "擦伤伴轻度扭伤", "risk_level": "low"},
            candidates,
        )

        self.assertEqual(
            result["options"][0]["medicine_ids"],
            ["medicine-17", "medicine-22", "medicine-20", "medicine-19"],
        )

    @patch("app.services.ai_service.settings")
    def test_large_local_inventory_is_narrowed_by_the_model_before_ranking(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            [
                {"ok": True, "reply": "外伤护理"},
                local_ranking_reply(
                    [
                        {
                            "option_id": "primary",
                            "label": "主方案",
                            "reason": "先清洁消毒再覆盖",
                            "medicine_ids": ["iodophor", "bandage"],
                        }
                    ]
                ),
            ]
        )
        candidates = [
            {
                "id": f"cold-{slot}",
                "slot": str(slot),
                "name": f"感冒用品{slot}",
                "category": "感冒发热",
                "indications": "用于常见感冒相关不适。",
            }
            for slot in range(1, 6)
        ] + [
            {
                "id": "iodophor",
                "slot": "17",
                "name": "碘伏消毒液",
                "category": "外伤护理",
                "indications": "用于浅表创面清洁消毒。",
            },
            {
                "id": "bandage",
                "slot": "20",
                "name": "创口贴",
                "category": "外伤护理",
                "indications": "用于清洁后覆盖保护。",
            },
        ]

        result = AiService(local_client=client).rank_inquiry_candidates(
            {"case_summary": "手部浅表擦伤", "risk_level": "low"},
            candidates,
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(
            result["options"][0]["medicine_ids"],
            ["iodophor", "bandage"],
        )
        ranking_prompt = client.messages_history[1][1]["content"]
        self.assertIn("碘伏消毒液", ranking_prompt)
        self.assertNotIn("感冒用品", ranking_prompt)

    @patch("app.services.ai_service.settings")
    def test_local_ranking_focuses_clear_heatstroke_case_before_model_selection(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        client = FakeLocalClient(
            local_ranking_reply(
                [
                    {
                        "option_id": "primary",
                        "label": "主方案",
                        "reason": "更贴合暑湿不适和头晕",
                        "medicine_ids": ["slot-08-huoxiang-zhengqi"],
                    }
                ]
            )
        )
        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "中暑后头晕，今天在外面晒了半天。",
                "observations": [
                    {"concept": "中暑", "status": "present", "evidence": "我有点中暑"},
                    {"concept": "头晕", "status": "present", "evidence": "有点头晕"},
                ],
                "duration": "半天",
                "used_medicines": "未使用",
                "allergy_or_contraindication": "无",
                "risk_level": "low",
                "vitals": {"temperature": 36.5, "heart_rate": 78, "spo2": 98},
            },
            [
                {
                    "id": "slot-01-fufang-ganmaoling",
                    "slot": "1",
                    "name": "复方感冒灵颗粒",
                    "category": "感冒发热",
                    "indications": "用于风寒感冒、头痛发热、鼻流清涕。",
                },
                {
                    "id": "slot-08-huoxiang-zhengqi",
                    "slot": "8",
                    "name": "藿香正气丸",
                    "category": "肠胃",
                    "indications": "解表化湿，理气和中。用于暑湿感冒、头痛身重、胸闷、呕吐泄泻。",
                },
            ],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["options"][0]["medicine_ids"], ["slot-08-huoxiang-zhengqi"])
        self.assertEqual(client.calls, 1)
        self.assertNotIn("复方感冒灵颗粒", client.last_messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
