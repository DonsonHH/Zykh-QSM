from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ai_service import AiService  # noqa: E402


class FakeHttpResponse:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class NoWeatherContext:
    def inquiry_context(self, _transcript, _existing):
        return None


class FakeLocalClient:
    def __init__(self, reply: str):
        self.reply = reply
        self.last_messages = []

    def chat(self, messages, **_kwargs):
        self.last_messages = messages
        return {"ok": True, "reply": self.reply}


def configure_cloud(mocked_settings) -> None:
    mocked_settings.ai_mode = "cloud"
    mocked_settings.ai_api_key = "test-key"
    mocked_settings.ai_api_key_file = Path("/nonexistent")
    mocked_settings.ai_api_base = "https://api.deepseek.com/chat/completions"
    mocked_settings.ai_responses_api_base = "https://api.deepseek.com/responses"
    mocked_settings.ai_model = "deepseek-v4-flash"
    mocked_settings.ai_enable_thinking = False
    mocked_settings.ai_chat_timeout_seconds = 35
    mocked_settings.ai_inquiry_enable_thinking = False
    mocked_settings.ai_inquiry_timeout_seconds = 45
    mocked_settings.ai_inquiry_attempt_timeout_seconds = 12
    mocked_settings.ai_inquiry_max_attempts = 1
    mocked_settings.ai_inquiry_retry_delay_seconds = 0
    mocked_settings.offline_inquiry_mode = "rules"


class AiServiceTest(unittest.TestCase):
    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_final_assessment_uses_responses_without_changing_the_public_result(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "assessment": {
                                            "summary": "咽痛和低热更符合常见上呼吸道不适。",
                                            "possible_conditions": [
                                                {
                                                    "name": "急性上呼吸道感染",
                                                    "likelihood": "more_likely",
                                                    "supporting_evidence_ids": ["obs-1"],
                                                    "non_supporting_evidence_ids": [],
                                                }
                                            ],
                                            "next_steps": ["休息并补充水分"],
                                            "seek_care_if": ["出现呼吸困难"],
                                        },
                                        "options": [
                                            {
                                                "option_id": "primary",
                                                "label": "主方案",
                                                "reason": "针对当前咽部不适。",
                                                "medicine_ids": ["m1"],
                                                "reason_by_medicine": {"m1": "用于当前咽部不适"},
                                                "usage_by_medicine": {"m1": "按说明书使用"},
                                            }
                                        ],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                    }
                ],
            }
        )

        result = AiService().rank_inquiry_candidates(
            {
                "case_summary": "咽痛伴低热",
                "evidence_catalog": {"obs-1": "咽痛：存在"},
            },
            [
                {
                    "id": "m1",
                    "name": "测试药",
                    "dosage": "按说明书使用",
                    "tags": ["咽喉"],
                    "contraindications": [],
                }
            ],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cloud_responses")
        self.assertEqual(
            result["assessment"]["possible_conditions"][0]["name"],
            "急性上呼吸道感染",
        )
        request = mocked_urlopen.call_args.args[0]
        request_payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.deepseek.com/responses")
        self.assertEqual(request_payload["reasoning"], {"effort": "low"})
        self.assertEqual(request_payload["max_output_tokens"], 8192)
        self.assertNotIn("messages", request_payload)

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_fast_extraction_repairs_non_boolean_state_before_returning_it(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        malformed = {
            "case_summary": "今早开始咽痛和头痛。",
            "observations": [
                {"concept": "咽痛", "status": "present", "evidence": "嗓子疼"},
                {"concept": "头痛", "status": "present", "evidence": "头有点痛"},
            ],
            "next_action": "ask",
            "assistant_reply": "除此之外还有其他明显不舒服吗？",
            "risk_level": "low",
            "clinical_ready": "false",
            "material_symptom_change": "false",
            "symptom_scope_complete": "false",
        }
        repaired = {
            **malformed,
            "clinical_ready": False,
            "material_symptom_change": False,
            "symptom_scope_complete": False,
        }
        mocked_urlopen.side_effect = [
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(malformed, ensure_ascii=False)},
                        }
                    ]
                }
            ),
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(repaired, ensure_ascii=False)},
                        }
                    ]
                }
            ),
        ]

        result = AiService(weather_context=NoWeatherContext()).extract_inquiry_information(
            "我今天早上开始嗓子疼，头也有点痛",
            {
                "conversation_turns": 1,
                "conversation": [],
                "symptom_followups_remaining": 4,
                "asked_clarifications": [],
                "clarification_answers": {},
            },
            {"name": "访客"},
        )

        self.assertTrue(result["ok"])
        self.assertIs(result["clinical_ready"], False)
        self.assertIs(result["material_symptom_change"], False)
        self.assertIs(result["symptom_scope_complete"], False)
        for call in mocked_urlopen.call_args_list:
            request = call.args[0]
            request_payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
            self.assertEqual(request_payload["thinking"], {"type": "disabled"})
            self.assertNotIn("reasoning", request_payload)

    @patch("app.services.ai_service.settings")
    def test_local_extraction_preserves_complaint_replacement_state(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "s": "实际是头痛，不是头晕。",
                    "f": [["头痛", "present", "其实是头痛", 2, 0.9]],
                    "n": "ask",
                    "q": "这次头痛是突然达到最痛，还是逐渐出现的？",
                    "change_type": "replace",
                    "replaced_concepts": ["头晕"],
                    "scope_complete": False,
                },
                ensure_ascii=False,
            )
        )

        result = AiService(
            local_client=client,
            weather_context=NoWeatherContext(),
        ).extract_inquiry_information(
            "我说错了，不是头晕，其实是头痛",
            {
                "conversation_turns": 2,
                "case_summary": "头晕",
                "observations": [
                    {"concept": "头晕", "status": "present", "evidence": "头晕"}
                ],
                "conversation": [],
            },
            {"name": "访客"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(result["symptom_change_type"], "replace")
        self.assertEqual(result["replaced_concepts"], ["头晕"])
        self.assertIs(result["symptom_scope_complete"], False)
        self.assertIn("不问能否站立或行走", client.last_messages[0]["content"])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_uses_the_same_structured_assessment_contract(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "summary": "板端模型已整理候选。",
                    "options": [],
                },
                ensure_ascii=False,
            )
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "暑热不适",
                "observations": [
                    {
                        "concept": "头晕",
                        "status": "present",
                        "evidence": "暴晒后头晕",
                    }
                ],
                "evidence_catalog": {"obs-1": "头晕：暴晒后头晕"},
            },
            [
                {
                    "id": "slot-08-huoxiang-zhengqi",
                    "name": "藿香正气丸",
                    "category": "肠胃",
                }
            ],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(result["summary"], "板端模型已整理候选。")
        self.assertEqual(result["options"], [])
        assessment = result["assessment"]
        self.assertIn("暑热", assessment["possible_conditions"][0]["name"])
        self.assertTrue(assessment["next_steps"])
        self.assertTrue(assessment["seek_care_if"])

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_guarded_dizziness_reply_does_not_reintroduce_a_mobility_template(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "目前考虑为脑供血不足，建议继续观察。"
                        }
                    }
                ]
            }
        )

        result = AiService(weather_context=NoWeatherContext()).chat("我有点头晕")

        self.assertTrue(result["ok"])
        self.assertNotIn("站立", result["reply"])
        self.assertNotIn("行走", result["reply"])
        self.assertIn("周围在转", result["reply"])

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_responses_timeout_falls_back_to_chat_after_one_12_second_attempt(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_settings.ai_inquiry_max_attempts = 2
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
                                        "assessment": {
                                            "summary": "现有信息仍需结合症状变化观察。",
                                            "possible_conditions": [],
                                            "next_steps": ["继续观察"],
                                            "seek_care_if": ["症状明显加重"],
                                        },
                                        "options": [],
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        }
                    ],
                }
            ),
        ]

        result = AiService().rank_inquiry_candidates(
            {"case_summary": "轻微不适"},
            [],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cloud_chat_fallback")
        self.assertEqual(result["assessment"]["next_steps"], ["继续观察"])
        self.assertEqual(mocked_urlopen.call_count, 2)
        requests = [call.args[0] for call in mocked_urlopen.call_args_list]
        timeouts = [call.kwargs["timeout"] for call in mocked_urlopen.call_args_list]
        self.assertEqual(requests[0].full_url, "https://api.deepseek.com/responses")
        self.assertEqual(requests[1].full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(timeouts[0], 12)

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_invalid_responses_output_falls_back_without_exposing_broken_json(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_settings.ai_inquiry_max_attempts = 2
        mocked_urlopen.side_effect = [
            FakeHttpResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "{not valid json"}
                            ],
                        }
                    ],
                }
            ),
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "assessment": {
                                            "summary": "未形成确定诊断。",
                                            "possible_conditions": [],
                                            "next_steps": ["继续观察症状变化"],
                                            "seek_care_if": ["症状明显加重"],
                                        },
                                        "options": [],
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        }
                    ],
                }
            ),
        ]

        result = AiService().rank_inquiry_candidates(
            {"case_summary": "信息有限"},
            [],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cloud_chat_fallback")
        self.assertEqual(result["assessment"]["summary"], "未形成确定诊断。")
        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_responses_attempt_timeout_is_capped_at_15_seconds(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_settings.ai_inquiry_attempt_timeout_seconds = 90
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "assessment": {
                                            "summary": "信息有限，继续观察变化。",
                                            "possible_conditions": [],
                                            "next_steps": ["记录症状变化"],
                                            "seek_care_if": ["症状明显加重"],
                                        },
                                        "options": [],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                    }
                ],
            }
        )

        result = AiService().rank_inquiry_candidates(
            {"case_summary": "轻微不适"},
            [],
        )

        self.assertEqual(result["source"], "cloud_responses")
        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 15)

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_final_ranking_falls_back_to_documented_chat_completion_contract(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_urlopen.side_effect = [
            FakeHttpResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "not json"}],
                        }
                    ],
                }
            ),
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "assessment": {
                                            "summary": "仍需结合症状变化观察。",
                                            "possible_conditions": [],
                                            "next_steps": ["继续观察"],
                                            "seek_care_if": ["症状明显加重"],
                                        },
                                        "options": [],
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        }
                    ]
                }
            ),
        ]

        result = AiService().rank_inquiry_candidates(
            {"case_summary": "轻微不适"},
            [],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cloud_chat_fallback")
        self.assertEqual(result["assessment"]["next_steps"], ["继续观察"])
        requests = [call.args[0] for call in mocked_urlopen.call_args_list]
        self.assertEqual(requests[0].full_url, "https://api.deepseek.com/responses")
        self.assertEqual(requests[1].full_url, "https://api.deepseek.com/chat/completions")
        chat_payload = json.loads(requests[1].data.decode("utf-8"))
        self.assertEqual(chat_payload["response_format"], {"type": "json_object"})
        self.assertIn("messages", chat_payload)

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_final_ranking_rejects_responses_without_the_business_contract(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_urlopen.side_effect = [
            FakeHttpResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {"unexpected": "provider shape is valid"},
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ),
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "assessment": {
                                            "summary": "信息有限，仍需结合变化继续观察。",
                                            "possible_conditions": [],
                                            "next_steps": ["记录症状变化"],
                                            "seek_care_if": ["症状明显加重"],
                                        },
                                        "options": [],
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        }
                    ]
                }
            ),
        ]

        result = AiService().rank_inquiry_candidates(
            {"case_summary": "轻微不适"},
            [],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cloud_chat_fallback")
        self.assertEqual(result["assessment"]["next_steps"], ["记录症状变化"])
        self.assertEqual(mocked_urlopen.call_count, 2)
        requests = [call.args[0] for call in mocked_urlopen.call_args_list]
        self.assertEqual(requests[0].full_url, "https://api.deepseek.com/responses")
        self.assertEqual(requests[1].full_url, "https://api.deepseek.com/chat/completions")

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_final_ranking_rejects_an_assessment_with_no_displayable_guidance(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        empty_assessment = {
            "summary": "只有摘要不会触发结果页的分析区域。",
            "possible_conditions": [],
            "next_steps": ["   "],
            "seek_care_if": [],
        }
        fallback_assessment = {
            "summary": "现有信息仍需结合变化观察。",
            "possible_conditions": [],
            "next_steps": ["记录症状变化"],
            "seek_care_if": ["症状明显加重"],
        }
        mocked_urlopen.side_effect = [
            FakeHttpResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {"assessment": empty_assessment, "options": []},
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ),
            FakeHttpResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {"assessment": fallback_assessment, "options": []},
                                    ensure_ascii=False,
                                )
                            },
                        }
                    ]
                }
            ),
        ]

        result = AiService().rank_inquiry_candidates(
            {"case_summary": "信息有限"},
            [],
        )

        self.assertEqual(result["source"], "cloud_chat_fallback")
        self.assertEqual(result["assessment"], fallback_assessment)
        self.assertEqual(mocked_urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
