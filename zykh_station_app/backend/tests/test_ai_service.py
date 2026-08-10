from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ai_service import AiService  # noqa: E402
from app.config import (  # noqa: E402
    _resolve_ai_mode,
    _resolve_offline_inquiry_mode,
    _resolve_inquiry_reasoning_effort,
)
from app.services.local_inquiry_status import local_inquiry_status  # noqa: E402


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


class SequenceLocalClient:
    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls = 0
        self.messages_history = []

    def chat(self, messages, **_kwargs):
        self.messages_history.append(messages)
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return {"ok": True, "reply": reply}


class UnavailableLocalClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, _messages, **_kwargs):
        self.calls += 1
        return {"ok": False, "error_message": "QSM model unavailable"}


class StatusLocalClient(UnavailableLocalClient):
    def status(self):
        return {
            "ok": False,
            "ready": False,
            "status": "unavailable",
            "model": "Qwen3.5-0.8B-Q4_K_M",
        }


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


def empty_local_ranking_reply(summary: str) -> str:
    return json.dumps(
        {
            "assessment": {
                "summary": summary,
                "possible_conditions": [],
                "next_steps": ["继续观察症状变化"],
                "seek_care_if": ["症状明显加重时及时联系医生"],
            },
            "options": [],
        },
        ensure_ascii=False,
    )


class AiServiceTest(unittest.TestCase):
    def test_high_risk_extract_contract_requires_a_nonempty_risk_signal(self) -> None:
        payload = {
            "case_summary": "用户描述明显不适。",
            "observations": [],
            "next_action": "escalate",
            "assistant_reply": "请尽快联系医生。",
            "risk_level": "high",
            "risk_signals": [],
        }

        self.assertFalse(AiService._valid_inquiry_extract_payload(payload))
        payload["risk_signals"] = ["用户原话中的危险表现"]
        self.assertTrue(AiService._valid_inquiry_extract_payload(payload))

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_medicine_guidance_requires_dynamic_safety_metadata_contract(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        guidance = {
            "indications": "用于测试症状",
            "dosage": "以实物包装说明书为准",
            "contraindications": ["测试辅料过敏者禁用"],
            "aliases": ["测试品牌名"],
            "active_ingredients": ["测试有效成分"],
            "structured_contraindications": [
                {
                    "concept_code": "ingredient_allergy",
                    "display_text": "测试辅料过敏者禁用",
                }
            ],
            "safety_note": "资料待药师核验",
        }
        mocked_urlopen.return_value = FakeHttpResponse(
            {"choices": [{"message": {"content": json.dumps(guidance, ensure_ascii=False)}}]}
        )

        with patch.object(AiService, "_cloud_reachable", return_value=True):
            result = AiService().generate_medicine_guidance(
                {
                    "name": "动态扫码药品",
                    "manufacturer": "测试厂家",
                    "barcode": "6900000000000",
                    "category": "家庭常用",
                    "spec": "0.3克×10袋",
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["guidance"]["active_ingredients"], ["测试有效成分"])
        request_payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        prompt = request_payload["messages"][0]["content"]
        self.assertIn("aliases", prompt)
        self.assertIn("active_ingredients", prompt)
        self.assertIn("structured_contraindications", prompt)

        incomplete = dict(guidance)
        incomplete.pop("active_ingredients")
        mocked_urlopen.return_value = FakeHttpResponse(
            {"choices": [{"message": {"content": json.dumps(incomplete, ensure_ascii=False)}}]}
        )
        with patch.object(AiService, "_cloud_reachable", return_value=True):
            rejected = AiService().generate_medicine_guidance(
                {"name": "动态扫码药品", "category": "家庭常用"}
            )
        self.assertFalse(rejected["ok"])
        self.assertIn("安全资料", rejected["error_message"])

    def test_reasoning_effort_defaults_off_for_fast_inquiry_and_honors_the_legacy_boolean(self) -> None:
        self.assertEqual(_resolve_inquiry_reasoning_effort(None, None), "off")
        self.assertEqual(_resolve_inquiry_reasoning_effort(None, "false"), "off")
        self.assertEqual(_resolve_inquiry_reasoning_effort(None, "true"), "high")
        self.assertEqual(_resolve_inquiry_reasoning_effort("low", "false"), "low")

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_inquiry_reasoning_effort_controls_cloud_extraction(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_settings.ai_inquiry_reasoning_effort = "high"
        mocked_settings.ai_inquiry_enable_thinking = False
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "case_summary": "头晕半天。",
                                    "observations": [],
                                    "next_action": "ask",
                                    "assistant_reply": "还有其他同时出现的不舒服吗？",
                                    "risk_level": "low",
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ]
            }
        )

        result = AiService(weather_context=NoWeatherContext()).extract_inquiry_information(
            "我头晕半天了",
            {"conversation_turns": 1, "conversation": []},
            {"name": "现场应急对象"},
        )

        self.assertTrue(result["ok"])
        request_payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_payload["thinking"], {"type": "enabled"})
        self.assertEqual(request_payload["reasoning_effort"], "high")
        self.assertNotIn("temperature", request_payload)

    @patch("app.services.local_inquiry_status.settings")
    def test_local_status_separates_model_health_from_rules_fallback(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.offline_inquiry_mode = "model"

        result = local_inquiry_status(
            {
                "ok": False,
                "ready": False,
                "status": "unavailable",
                "model": "Qwen3.5-0.8B-Q4_K_M",
            }
        )

        self.assertFalse(result["ready"])
        self.assertFalse(result["model_ready"])
        self.assertTrue(result["rules_fallback_ready"])
        self.assertEqual(result["primary"], "model")
        self.assertEqual(result["fallback"], "rules")

    @patch("app.services.ai_service.settings")
    def test_ai_status_exposes_both_offline_readiness_signals(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "auto"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        mocked_settings.ai_model = "deepseek-v4-flash"
        mocked_settings.offline_inquiry_mode = "model"

        result = AiService(local_client=StatusLocalClient()).status()

        self.assertFalse(result["local"]["ready"])
        self.assertFalse(result["model_ready"])
        self.assertTrue(result["rules_fallback_ready"])
        self.assertTrue(result["offline_inquiry_ready"])

    def test_cloud_first_inquiry_defaults_to_rules_only_as_failure_continuity(self) -> None:
        self.assertEqual(_resolve_ai_mode(None), "cloud")
        self.assertEqual(_resolve_ai_mode("local"), "cloud")
        self.assertEqual(_resolve_ai_mode("auto"), "cloud")
        self.assertEqual(_resolve_offline_inquiry_mode(None), "rules")
        self.assertEqual(_resolve_offline_inquiry_mode(""), "rules")
        self.assertEqual(_resolve_offline_inquiry_mode("rules"), "rules")
        self.assertEqual(_resolve_offline_inquiry_mode("model"), "rules")

    @patch("app.services.ai_service.settings")
    def test_local_model_failure_uses_rules_only_for_dialogue_continuity(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = UnavailableLocalClient()

        result = AiService(local_client=client).extract_inquiry_information(
            "我头晕半天了",
            {"conversation_turns": 1, "conversation": []},
            {"name": "现场应急对象"},
        )

        self.assertEqual(client.calls, 1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["case_summary"], "头晕不适")

    @patch("app.services.ai_service.urlopen", side_effect=TimeoutError("cloud timeout"))
    @patch("app.services.ai_service.settings")
    def test_cloud_failure_uses_rules_without_calling_the_qsm_model(
        self,
        mocked_settings,
        _mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_settings.ai_mode = "cloud"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "case_summary": "头晕半天。",
                    "observations": [
                        {
                            "concept": "头晕",
                            "status": "present",
                            "evidence": "头晕半天",
                            "source_turn": 1,
                            "confidence": 0.9,
                        }
                    ],
                    "next_action": "ask",
                    "assistant_reply": "还有其他同时出现的不舒服吗？",
                    "risk_level": "low",
                },
                ensure_ascii=False,
            )
        )

        result = AiService(
            local_client=client,
            weather_context=NoWeatherContext(),
        ).extract_inquiry_information(
            "我头晕半天了",
            {"conversation_turns": 1, "conversation": []},
            {"name": "现场应急对象"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "offline_rules")
        self.assertEqual(client.last_messages, [])

    @patch("app.services.ai_service.settings")
    def test_cloud_unavailable_never_lets_rules_select_medicines(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "cloud"
        mocked_settings.offline_inquiry_mode = "rules"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")

        result = AiService().rank_inquiry_candidates(
            {"case_summary": "成人水样腹泻，能喝水，没有便血或持续高热"},
            [
                {
                    "id": "slot-03-diosmectite",
                    "name": "蒙脱石散",
                    "category": "肠胃",
                },
                {
                    "id": "slot-09-bifid-triple",
                    "name": "双歧杆菌三联活菌肠溶胶囊",
                    "category": "肠胃",
                },
            ],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["options"], [])

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.AiService._cloud_reachable", return_value=False)
    @patch("app.services.ai_service.settings")
    def test_legacy_auto_mode_uses_rules_when_cloud_is_unreachable(
        self,
        mocked_settings,
        _mocked_cloud_reachable,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_settings.ai_mode = "auto"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "case_summary": "头晕半天。",
                    "observations": [],
                    "next_action": "ask",
                    "assistant_reply": "还有其他同时出现的不舒服吗？",
                    "risk_level": "low",
                },
                ensure_ascii=False,
            )
        )

        result = AiService(
            local_client=client,
            weather_context=NoWeatherContext(),
        ).extract_inquiry_information(
            "我头晕半天了",
            {"conversation_turns": 1, "conversation": []},
            {"name": "现场应急对象"},
        )

        self.assertEqual(result["source"], "offline_rules")
        self.assertEqual(client.last_messages, [])
        mocked_urlopen.assert_not_called()

    @patch("app.services.ai_service.settings")
    def test_local_model_failure_never_lets_rules_select_medicine(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = UnavailableLocalClient()

        result = AiService(local_client=client).rank_inquiry_candidates(
            {"case_summary": "头晕不适"},
            [{"id": "m1", "name": "测试药", "category": "测试"}],
        )

        self.assertEqual(client.calls, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["options"], [])

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_final_assessment_uses_responses_without_changing_the_public_result(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        mocked_settings.ai_inquiry_reasoning_effort = "high"
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
        self.assertEqual(request_payload["reasoning"], {"effort": "high"})
        self.assertEqual(request_payload["max_output_tokens"], 8192)
        self.assertNotIn("messages", request_payload)

    @patch("app.services.ai_service.urlopen")
    @patch("app.services.ai_service.settings")
    def test_final_ranking_sends_only_authorized_combinations_and_requires_their_token(
        self,
        mocked_settings,
        mocked_urlopen,
    ) -> None:
        configure_cloud(mocked_settings)
        authorized = {
            "combination_id": "adult-watery-diarrhea-separated",
            "label": "成人水样腹泻分时用药",
            "medicine_ids": ["m1", "m2"],
            "reviewed_usage_by_medicine": {
                "m1": "先按说明书使用。",
                "m2": "间隔至少 2 小时后按说明书使用。",
            },
            "authorization_fingerprint": "authorization-token",
        }
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
                                            "summary": "当前符合受控分时方案的适用条件。",
                                            "possible_conditions": [],
                                            "next_steps": ["优先补液"],
                                            "seek_care_if": ["出现便血或持续高热"],
                                        },
                                        "options": [
                                            {
                                                "option_id": "primary",
                                                "label": "分时方案",
                                                "reason": "符合当前病例条件。",
                                                "combination_id": authorized[
                                                    "combination_id"
                                                ],
                                                "authorization_fingerprint": authorized[
                                                    "authorization_fingerprint"
                                                ],
                                                "medicine_ids": authorized["medicine_ids"],
                                                "reason_by_medicine": {},
                                                "usage_by_medicine": {},
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
            {"case_summary": "成人低风险水样腹泻"},
            [{"id": "m1"}, {"id": "m2"}],
            allowed_combinations=[authorized],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["options"][0]["combination_id"],
            authorized["combination_id"],
        )
        request_payload = json.loads(
            mocked_urlopen.call_args.args[0].data.decode("utf-8")
        )
        model_input = json.loads(request_payload["input"])
        self.assertEqual(model_input["allowed_combinations"], [authorized])
        self.assertIn("不能自由拼接多个药品", request_payload["instructions"])
        self.assertEqual(request_payload["reasoning"], {"effort": "none"})

    def test_final_ranking_contract_rejects_free_form_multi_medicine_options(self) -> None:
        base = {
            "assessment": {
                "summary": "仍需观察。",
                "possible_conditions": [],
                "next_steps": ["继续观察"],
                "seek_care_if": ["症状加重"],
            },
            "options": [
                {
                    "option_id": "primary",
                    "label": "模型自由拼药",
                    "reason": "不应被接受",
                    "medicine_ids": ["m1", "m2"],
                }
            ],
        }

        self.assertFalse(AiService._valid_inquiry_ranking_payload(base))
        base["options"][0].update(
            {
                "combination_id": "approved-combination",
                "authorization_fingerprint": "authorization-token",
            }
        )
        self.assertTrue(AiService._valid_inquiry_ranking_payload(base))

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
                    "ct": "replace",
                    "rc": ["头晕"],
                    "sc": False,
                    "at": ["main_symptom"],
                    "te": {"main_symptom": "其实是头痛"},
                    "qt": "headache_onset",
                    "cr": False,
                    "mc": True,
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
        self.assertEqual(result["answered_topics_this_turn"], ["main_symptom"])
        self.assertEqual(result["topic_evidence"], {"main_symptom": "其实是头痛"})
        self.assertEqual(result["question_topic"], "headache_onset")
        self.assertIs(result["clinical_ready"], False)
        self.assertIs(result["material_symptom_change"], True)
        self.assertIn("不问能否站立或行走", client.last_messages[0]["content"])
        self.assertIn("at=本轮已答主题", client.last_messages[0]["content"])
        self.assertIn("qt=下一问主题", client.last_messages[0]["content"])
        self.assertIn("cr=信息足够", client.last_messages[0]["content"])

    @patch("app.services.ai_service.settings")
    def test_local_extraction_rejects_the_same_invalid_boolean_contract_as_cloud(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "case_summary": "头晕半天。",
                    "observations": [
                        {
                            "concept": "头晕",
                            "status": "present",
                            "evidence": "头晕半天",
                            "source_turn": 1,
                            "confidence": 0.9,
                        }
                    ],
                    "next_action": "ask",
                    "assistant_reply": "有没有其他同时出现的不舒服？",
                    "risk_level": "low",
                    "clinical_ready": "false",
                },
                ensure_ascii=False,
            )
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "我头晕半天了",
            {"conversation_turns": 1, "conversation": []},
            {"name": "现场应急对象"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertNotIsInstance(result.get("clinical_ready"), str)

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_rejects_an_incomplete_business_contract(
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

        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["options"], [])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_calls_the_model_for_an_empty_safe_pool(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = SequenceLocalClient(
            [empty_local_ranking_reply("目前没有通过安全核验的药品候选。")]
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "头晕半天",
                "observations": [
                    {
                        "concept": "头晕",
                        "status": "present",
                        "evidence": "头晕半天",
                    }
                ],
                "evidence_catalog": {"obs-1": "头晕：头晕半天"},
            },
            [],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(
            result["assessment"]["summary"],
            "目前没有通过安全核验的药品候选。",
        )
        self.assertEqual(result["options"], [])
        self.assertEqual(client.calls, 1)
        local_payload = json.loads(client.messages_history[0][1]["content"])
        self.assertEqual(local_payload["catalog"], [])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_calls_the_assessment_model_after_empty_category_narrowing(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = SequenceLocalClient(
            [
                "NONE",
                empty_local_ranking_reply("现有安全候选与当前不适没有直接关系。"),
            ]
        )
        candidates = [
            {
                "id": f"medicine-{index}",
                "name": f"测试药品{index}",
                "category": "感冒发热" if index % 2 else "外伤护理",
                "indications": "与当前头晕没有直接关系。",
            }
            for index in range(7)
        ]

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "头晕半天",
                "observations": [
                    {
                        "concept": "头晕",
                        "status": "present",
                        "evidence": "头晕半天",
                    }
                ],
                "evidence_catalog": {"obs-1": "头晕：头晕半天"},
            },
            candidates,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(
            result["assessment"]["summary"],
            "现有安全候选与当前不适没有直接关系。",
        )
        self.assertEqual(result["options"], [])
        self.assertEqual(client.calls, 2)
        local_payload = json.loads(client.messages_history[1][1]["content"])
        self.assertEqual(local_payload["catalog"], [])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_returns_the_model_assessment_contract(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "assessment": {
                        "summary": "头晕需要结合持续时间与体征继续观察。",
                        "possible_conditions": [
                            {
                                "name": "常见头晕相关原因",
                                "likelihood": "possible",
                                "supporting_evidence_ids": ["obs-1"],
                                "non_supporting_evidence_ids": [],
                            }
                        ],
                        "next_steps": ["补充水分并休息"],
                        "seek_care_if": ["出现胸痛或呼吸困难"],
                    },
                    "options": [
                        {
                            "option_id": "primary",
                            "label": "主方案",
                            "reason": "与当前已核对的不适相关。",
                            "medicine_ids": ["m1"],
                            "reason_by_medicine": {"m1": "用于核对当前不适"},
                            "usage_by_medicine": {"m1": "按说明书使用"},
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "头晕半天",
                "observations": [
                    {
                        "concept": "头晕",
                        "status": "present",
                        "evidence": "头晕半天",
                    }
                ],
                "evidence_catalog": {"obs-1": "头晕：头晕半天"},
            },
            [
                {
                    "id": "m1",
                    "name": "测试药",
                    "category": "测试",
                    "indications": "测试用途",
                    "dosage": "按说明书使用",
                    "contraindications": [],
                    "tags": ["头晕"],
                    "safety_note": "核对说明书",
                }
            ],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(
            result["assessment"]["summary"],
            "头晕需要结合持续时间与体征继续观察。",
        )
        self.assertEqual(result["options"][0]["medicine_ids"], ["m1"])
        self.assertEqual(
            result["options"][0]["reason_by_medicine"],
            {"m1": "用于核对当前不适"},
        )
        self.assertEqual(
            result["options"][0]["usage_by_medicine"],
            {"m1": "按说明书使用"},
        )
        local_system_prompt = client.last_messages[0]["content"]
        self.assertIn("assessment", local_system_prompt)
        self.assertIn("possible_conditions", local_system_prompt)
        self.assertIn("medicine_ids", local_system_prompt)
        self.assertNotIn("A=", local_system_prompt)
        local_payload = json.loads(client.last_messages[1]["content"])
        self.assertEqual(
            local_payload["case"]["x"],
            {"obs-1": "头晕：头晕半天"},
        )
        catalog_text = json.dumps(local_payload["catalog"], ensure_ascii=False)
        self.assertIn("m1", catalog_text)
        self.assertIn("按说明书使用", catalog_text)
        self.assertIn("核对说明书", catalog_text)

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_rejects_an_option_with_any_unknown_id(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "assessment": {
                        "summary": "测试排序结果。",
                        "possible_conditions": [],
                        "next_steps": ["继续观察"],
                        "seek_care_if": ["症状加重时联系医生"],
                    },
                    "options": [
                        {
                            "option_id": "primary",
                            "label": "主方案",
                            "reason": "测试",
                            "medicine_ids": ["m1", "hallucinated-id"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {
                "case_summary": "头晕半天",
                "observations": [],
                "evidence_catalog": {},
            },
            [
                {
                    "id": "m1",
                    "name": "测试药",
                    "category": "测试",
                    "indications": "测试用途",
                }
            ],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["options"], [])

    @patch("app.services.ai_service.settings")
    def test_local_candidate_ranking_rejects_duplicate_ids_in_one_option(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.offline_inquiry_mode = "model"
        client = FakeLocalClient(
            json.dumps(
                {
                    "assessment": {
                        "summary": "测试排序结果。",
                        "possible_conditions": [],
                        "next_steps": ["继续观察"],
                        "seek_care_if": ["症状加重时联系医生"],
                    },
                    "options": [
                        {
                            "option_id": "primary",
                            "label": "主方案",
                            "reason": "测试",
                            "medicine_ids": ["m1", "m1"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

        result = AiService(local_client=client).rank_inquiry_candidates(
            {"case_summary": "头晕半天", "observations": [], "evidence_catalog": {}},
            [{"id": "m1", "name": "测试药", "category": "测试"}],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "rules_fallback")
        self.assertEqual(result["options"], [])

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
        mocked_settings.ai_inquiry_reasoning_effort = "high"
        mocked_settings.ai_enable_thinking = False
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
        self.assertEqual(chat_payload["thinking"], {"type": "enabled"})
        self.assertEqual(chat_payload["reasoning_effort"], "high")
        self.assertNotIn("temperature", chat_payload)

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
