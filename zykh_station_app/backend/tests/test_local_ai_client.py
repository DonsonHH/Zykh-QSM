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

    def chat(self, *_args, **_kwargs) -> dict[str, object]:
        self.calls += 1
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

    def test_rules_reply_does_not_duplicate_terminal_punctuation(self) -> None:
        reply = AiService(local_client=FakeLocalClient({"ok": False}))._rules_reply(
            "我有些头晕。", "offline"
        )["reply"]

        self.assertNotIn("头晕。。", reply)

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
                        "symptom_dimensions": ["感冒鼻部症状"],
                        "dimension_evidence": {"感冒鼻部症状": "轻微流涕"},
                        "duration": "",
                        "used_medicines": "",
                        "allergy_or_contraindication": "",
                        "follow_up_question": "这种情况持续多久了？",
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
        self.assertEqual(result["symptom_dimensions"], ["感冒鼻部症状"])
        self.assertNotIn("risk_level", result)


if __name__ == "__main__":
    unittest.main()
