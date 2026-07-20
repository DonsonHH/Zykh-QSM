from __future__ import annotations

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import InquiryEvaluateRequest  # noqa: E402
from app.services.ai_service import AiService  # noqa: E402
from app.services.inquiry_service import InquiryService  # noqa: E402
from app.services.local_ai_client import LocalAiClient  # noqa: E402


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


class RecordingOpener:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout: float):
        self.requests.append((request, timeout))
        payload = self.payloads.pop(0)
        return FakeResponse(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class FakeLocalClient:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls = 0
        self.last_messages = []
        self.last_kwargs = {}

    def chat(self, messages, **kwargs) -> dict[str, object]:
        self.calls += 1
        self.last_messages = messages
        self.last_kwargs = kwargs
        return dict(self.result)

    def status(self) -> dict[str, object]:
        return {"ok": True, "ready": True, "status": "ready"}


LOCAL_SETTINGS = SimpleNamespace(
    local_ai_base_url="http://127.0.0.1:18083",
    local_ai_health_path="/health",
    local_ai_chat_path="/v1/chat/completions",
    local_ai_model="Qwen3.5-0.8B-Q4_K_M",
    local_ai_health_timeout_seconds=2,
    local_ai_timeout_seconds=120,
)


class LocalAiClientTest(unittest.TestCase):
    @patch("app.services.local_ai_client.settings", LOCAL_SETTINGS)
    def test_status_reports_ready_from_llama_health(self) -> None:
        opener = RecordingOpener([{"status": "ok"}])

        result = LocalAiClient(opener=opener).status()

        self.assertTrue(result["ready"])
        self.assertEqual(result["model"], "Qwen3.5-0.8B-Q4_K_M")
        self.assertEqual(opener.requests[0][0].full_url, "http://127.0.0.1:18083/health")

    @patch("app.services.local_ai_client.settings", LOCAL_SETTINGS)
    def test_chat_uses_openai_compatible_endpoint(self) -> None:
        opener = RecordingOpener(
            [{"choices": [{"message": {"content": "请补充症状持续时间。"}}]}]
        )
        client = LocalAiClient(opener=opener)

        result = client.chat([{"role": "user", "content": "我头晕"}], max_tokens=80)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(result["reply"], "请补充症状持续时间。")
        request = opener.requests[0][0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18083/v1/chat/completions")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "Qwen3.5-0.8B-Q4_K_M")
        self.assertFalse(body["stream"])

    @patch("app.services.local_ai_client.settings", LOCAL_SETTINGS)
    def test_connection_failure_is_structured(self) -> None:
        def failing_opener(*_args, **_kwargs):
            raise URLError("offline model stopped")

        result = LocalAiClient(opener=failing_opener).status()

        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("offline model stopped", result["error_message"])


class AiServiceOfflineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            ai_mode="local",
            ai_api_key="",
            ai_api_key_file=Path("/nonexistent"),
            ai_model="cloud-model",
        )

    @patch("app.services.ai_service.settings")
    def test_local_mode_uses_real_local_model(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {"ok": True, "source": "local_llm", "model": "qwen", "reply": "请说明头晕持续多久。"}
        )
        service = AiService(local_client=client)
        service._system_prompt = lambda: "safe system prompt"

        result = service.chat("我头晕")

        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(client.calls, 1)

    @patch("app.services.ai_service.settings")
    def test_emergency_rule_runs_before_model(self, mocked_settings) -> None:
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient({"ok": True, "reply": "unused"})

        result = AiService(local_client=client).chat("我现在胸痛并且呼吸困难")

        self.assertEqual(result["source"], "safety_rules")
        self.assertEqual(client.calls, 0)
        self.assertIn("立即联系", result["reply"])

    @patch("app.services.ai_service.settings")
    def test_negated_emergency_terms_do_not_trigger_rule(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {"ok": True, "source": "local_llm", "model": "qwen", "reply": "头晕持续多久了？"}
        )
        service = AiService(local_client=client)
        service._system_prompt = lambda: "safe system prompt"

        result = service.chat("我轻微头晕，没有胸痛，也没有呼吸困难")

        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(client.calls, 1)

    def test_unrelieved_chest_pain_still_matches_emergency_rule(self) -> None:
        self.assertTrue(AiService._has_unnegated_term("胸痛一直没有缓解", "胸痛"))

    def test_diagnostic_claim_is_replaced_by_safe_followup(self) -> None:
        service = AiService(local_client=FakeLocalClient({"ok": True}))

        reply = service._guard_reply("你属于轻症，无需紧急处理，以排除脑供血不足。", "我头晕")

        self.assertNotIn("属于轻症", reply)
        self.assertNotIn("排除", reply)
        self.assertIn("不能判断病因", reply)

    def test_named_disease_speculation_is_replaced_by_safe_followup(self) -> None:
        service = AiService(local_client=FakeLocalClient({"ok": True}))

        reply = service._guard_reply(
            "头晕需警惕脑血管意外或低血压等风险，切勿自行用药。",
            "我有些头晕，没有胸痛。",
        )

        self.assertNotIn("脑血管意外", reply)
        self.assertNotIn("低血压", reply)
        self.assertIn("不能判断病因", reply)

    def test_guarded_followup_matches_reported_symptom_group(self) -> None:
        service = AiService(local_client=FakeLocalClient({"ok": True}))

        reply = service._guard_reply("考虑为呼吸道感染。", "轻微咳嗽刚开始")

        self.assertIn("是否伴有发热或呼吸费力", reply)
        self.assertNotIn("视物模糊", reply)

    def test_long_model_analysis_keeps_only_last_followup_question(self) -> None:
        reply = AiService._compact_chat_reply(
            "当前信息较多，需要继续整理。" * 10 + "请问你最近是否服用过上述任何药品？"
        )

        self.assertEqual(reply, "请问你最近是否服用过任何药物？")

    def test_short_model_reply_does_not_reference_hidden_inventory(self) -> None:
        reply = AiService._compact_chat_reply("您是否正在服用上述列出的任何药物？")

        self.assertEqual(reply, "您是否正在服用任何药物？")

    def test_numbered_followups_keep_only_first_complete_question(self) -> None:
        reply = AiService._compact_chat_reply(
            "需要补充关键信息以便继续分析：1.咳嗽持续了多久？"
            "2.是否有发热或喉咙痛？3.近期使用过哪些药物？"
        )

        self.assertEqual(reply, "咳嗽持续了多久？")

    def test_continuity_reply_hides_internal_fallback_details(self) -> None:
        reply = AiService(local_client=FakeLocalClient({"ok": False}))._rules_reply(
            "我有些头晕。", "offline"
        )["reply"]

        self.assertNotIn("头晕。。", reply)
        self.assertNotIn("规则", reply)
        self.assertNotIn("模型", reply)
        self.assertNotIn("暂不可用", reply)

    def test_recommendation_language_removes_efficacy_promises(self) -> None:
        result = AiService._normalize_recommendation_language(
            {
                "summary": "这个方案一定有效，可以治好当前不适。",
                "option_reasons": {"A": "这个方案见效快、快速缓解并且保证有效。"},
            },
            ["A"],
            "cloud",
        )

        combined = result["summary"] + result["option_reasons"]["A"]
        self.assertTrue(result["ok"])
        self.assertNotIn("见效快", combined)
        self.assertNotIn("快速缓解", combined)
        self.assertNotIn("一定有效", combined)
        self.assertNotIn("可以治好", combined)
        self.assertNotIn("保证有效", combined)

    def test_definitive_local_model_safety_notice_is_ignored(self) -> None:
        self.assertEqual(InquiryService._safe_ai_notice("无禁忌，可以服用"), "")
        self.assertEqual(
            InquiryService._safe_ai_notice("使用前请核对既往过敏与说明书。"),
            "使用前请核对既往过敏与说明书。",
        )

    @patch("app.services.ai_service.settings")
    def test_inquiry_fact_extraction_can_come_from_local_model(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": json.dumps(
                    {
                        "case_summary": "轻微流涕。",
                        "observations": [
                            {
                                "concept": "轻微流涕",
                                "status": "present",
                                "evidence": "轻微流涕",
                                "source_turn": 1,
                                "confidence": 0.9,
                            }
                        ],
                        "duration": "",
                        "used_medicines": "",
                        "allergy_or_contraindication": "",
                        "next_question": "这种情况持续多久了？",
                        "next_action": "ask",
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                ),
            }
        )
        service = AiService(local_client=client)

        result = service.extract_inquiry_information("轻微流涕", {}, {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(result["observations"][0]["concept"], "轻微流涕")
        self.assertNotIn("risk_level", result)

    @patch("app.services.ai_service.settings")
    def test_local_inquiry_extraction_uses_a_small_but_complete_json_budget(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": json.dumps(
                    {
                        "s": "头晕持续半天。",
                        "f": [["暑热后头晕", "present", "头晕", 1, 0.86]],
                        "du": "半天",
                        "m": "未使用",
                        "a": "无",
                        "q": "有没有恶心或腹泻？",
                        "n": "ask",
                        "r": "已确认头晕持续半天。",
                        "c": 0.86,
                    },
                    ensure_ascii=False,
                ),
            }
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "我头晕半天了，没有用药，也没有过敏",
            {},
            {"age": 65},
        )

        self.assertEqual(client.last_kwargs["max_tokens"], 72)
        self.assertLess(len(client.last_messages[0]["content"]), 520)
        self.assertIn('"f"', client.last_messages[1]["content"])
        self.assertEqual(result["observations"][0]["concept"], "暑热后头晕")
        self.assertEqual(result["next_question"], "有没有恶心或腹泻？")

    @patch("app.services.ai_service.settings")
    def test_local_inquiry_recovers_complete_facts_from_a_truncated_outer_object(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": (
                    '{"summary":"头晕脑胀伴冷汗","facts":['
                    '{"concept":"头晕脑胀","status":"present","evidence":"我有点头晕脑胀"},'
                    '{"concept":"冷汗","status":"present","evidence":"还冒冷汗"}],'
                    '"action":"ask",'
                ),
            }
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "我有点头晕脑胀，还冒冷汗",
            {"conversation_turns": 1, "conversation": []},
            {"age": 65},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [item["concept"] for item in result["observations"]],
            ["头晕脑胀", "冷汗"],
        )
        self.assertEqual(result["next_question"], "这种不舒服大概持续多久了？")

    @patch("app.services.ai_service.settings")
    def test_local_inquiry_prompt_names_the_field_answered_by_a_short_reply(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": '{"n":"ask","q":"有没有药物过敏？","m":"未使用"}',
            }
        )
        existing = {
            "conversation_turns": 4,
            "case_summary": "暑热后头晕",
            "duration": "半天多",
            "conversation": [
                {"role": "user", "content": "我有些中暑头晕"},
                {"role": "assistant", "content": "这种不舒服大概持续多久了？"},
                {"role": "user", "content": "半天多"},
                {"role": "assistant", "content": "这次不舒服以后有没有用过药？"},
            ],
        }

        result = AiService(local_client=client).extract_inquiry_information("药", existing, {})
        prompt = json.loads(client.last_messages[1]["content"])

        self.assertEqual(prompt["known"]["target"]["field"], "used_medicines")
        self.assertEqual(result["used_medicines"], "未使用")

    @patch("app.services.ai_service.settings")
    def test_explicit_duration_answer_is_merged_without_calling_the_small_model(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient({"ok": True, "reply": '{"duration":"半天多"}'})
        existing = {
            "conversation_turns": 2,
            "case_summary": "晒后头晕",
            "duration": "",
            "conversation": [
                {"role": "assistant", "content": "这种不舒服大概持续多久了？"},
            ],
        }

        result = AiService(local_client=client).extract_inquiry_information("半天多", existing, {})

        self.assertEqual(client.last_messages, [])
        self.assertEqual(result["duration"], "半天多")
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["next_question"], "这次不舒服以后有没有用过药？")

    @patch("app.services.ai_service.settings")
    def test_short_no_to_a_clinical_follow_up_becomes_an_absent_fact(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient({"ok": True, "reply": '{"n":"ask"}'})
        existing = {
            "conversation_turns": 3,
            "case_summary": "晒后头晕",
            "conversation": [
                {"role": "assistant", "content": "有没有恶心或腹泻？"},
            ],
        }

        result = AiService(local_client=client).extract_inquiry_information("没有", existing, {})

        self.assertEqual(client.last_messages, [])
        self.assertEqual(result["observations"][0]["concept"], "恶心或腹泻")
        self.assertEqual(result["observations"][0]["status"], "absent")
        self.assertEqual(result["observations"][0]["evidence"], "没有")
        self.assertEqual(result["next_question"], "这种不舒服大概持续多久了？")

    @patch("app.services.ai_service.settings")
    def test_partial_small_model_json_continues_with_one_natural_question(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": '{"s":"暑热后头晕","d":["头晕"]}',
            }
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "在外面晒了以后有点头晕",
            {"conversation_turns": 1, "conversation": []},
            {"age": 65},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_llm")
        self.assertEqual(result["next_action"], "ask")
        self.assertEqual(result["assistant_reply"], "这种不舒服大概持续多久了？")
        self.assertEqual(result["observations"][0]["evidence"], "在外面晒了以后有点头晕")

    @patch("app.services.ai_service.settings")
    def test_small_model_fragment_is_not_shown_as_a_follow_up_question(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": '{"target":"头晕","question":"头晕","answer":"头晕"}',
            }
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "我今天在外面晒后有点头晕",
            {"conversation_turns": 1, "conversation": []},
            {},
        )

        self.assertFalse(result["ok"])
        self.assertIn("换一种说法", result["message"])

    @patch("app.services.ai_service.settings")
    def test_local_model_cannot_repeat_the_opening_after_extracting_a_complaint(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": (
                    '{"s":"头晕、暑湿不适","d":["头晕"],"p":["暑湿不适"],'
                    '"n":"ask","q":"今天哪里不舒服？慢慢说。","k":"low","c":0.7}'
                ),
            }
        )

        result = AiService(local_client=client).extract_inquiry_information(
            "我今天在外面晒了以后有点头晕恶心",
            {
                "conversation_turns": 1,
                "conversation": [
                    {"role": "assistant", "content": "今天哪里不舒服？慢慢说。"},
                ],
            },
            {},
        )

        self.assertEqual(result["case_summary"], "头晕、暑湿不适")
        self.assertEqual(result["assistant_reply"], "这种不舒服大概持续多久了？")
        self.assertNotIn("哪里不舒服", result["next_question"])

    @patch("app.services.ai_service.settings")
    def test_local_prompt_keeps_only_recent_compact_conversation(
        self,
        mocked_settings,
    ) -> None:
        mocked_settings.ai_mode = "local"
        mocked_settings.ai_api_key = ""
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        client = FakeLocalClient(
            {
                "ok": True,
                "reply": '{"s":"头晕","d":["头晕"],"n":"ask","q":"持续多久了？"}',
            }
        )
        conversation = [
            {"role": "user", "content": f"第{index}轮" + "很长的描述" * 40}
            for index in range(10)
        ]

        AiService(local_client=client).extract_inquiry_information(
            "我头晕",
            {
                "conversation_turns": 10,
                "conversation": conversation,
                "recent_history": [
                    {"title": "旧问询", "reply": "旧结论" * 80},
                ],
            },
            {},
        )

        payload = json.loads(client.last_messages[1]["content"])
        self.assertEqual(len(payload["known"]["c"]), 6)
        self.assertTrue(payload["known"]["c"][0]["x"].startswith("第4轮"))
        self.assertLessEqual(len(payload["known"]["c"][0]["x"]), 80)
        self.assertLessEqual(len(payload["known"]["h"][0]["summary"]), 80)

    def test_compact_local_schema_accepts_small_model_object_variants(self) -> None:
        result = AiService._expand_local_inquiry(
            {
                "s": "用户明确提到头孢过敏。",
                "f": [["药物过敏史", "present", "对头孢过敏", 1, 0.98]],
                "a": "对头孢过敏",
                "n": "ask",
            }
        )

        self.assertEqual(result["allergy_or_contraindication"], "对头孢过敏")
        self.assertEqual(result["observations"][0]["concept"], "药物过敏史")


if __name__ == "__main__":
    unittest.main()
