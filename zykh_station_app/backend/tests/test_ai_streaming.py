from __future__ import annotations

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ai_service import AiService  # noqa: E402
from app.services.local_ai_client import LocalAiClient  # noqa: E402


class StreamingResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def sse(*events: dict[str, object] | str) -> bytes:
    chunks = []
    for event in events:
        data = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
        chunks.append(f"data: {data}\n\n")
    return "".join(chunks).encode("utf-8")


class AiStreamingTest(unittest.TestCase):
    def test_local_client_yields_real_provider_deltas(self) -> None:
        payload = sse(
            {"choices": [{"delta": {"content": "请说明"}}]},
            {"choices": [{"delta": {"content": "头晕多久。"}}]},
            "[DONE]",
        )
        client = LocalAiClient(opener=lambda *_args, **_kwargs: StreamingResponse(payload))

        events = list(client.stream([{"role": "user", "content": "头晕"}], max_tokens=80))

        self.assertEqual([event["text"] for event in events if event["type"] == "delta"], ["请说明", "头晕多久。"])
        self.assertEqual(events[-1]["type"], "done")

    @patch("app.services.ai_service.settings")
    def test_cloud_stream_ignores_reasoning_and_yields_answer(self, mocked_settings) -> None:
        mocked_settings.ai_mode = "auto"
        mocked_settings.ai_api_key = "private"
        mocked_settings.ai_api_key_file = Path("/nonexistent")
        mocked_settings.ai_api_base = "https://api.deepseek.com/chat/completions"
        mocked_settings.ai_model = "deepseek-v4-flash"
        mocked_settings.ai_enable_thinking = True
        mocked_settings.ai_chat_timeout_seconds = 30
        mocked_settings.network_preferred_mode = "sim"
        payload = sse(
            {"choices": [{"delta": {"reasoning_content": "内部推理"}}]},
            {"choices": [{"delta": {"content": "头晕持续多久？"}}]},
            "[DONE]",
        )
        service = AiService()
        service._system_prompt = lambda: "安全提示"
        service._cloud_reachable = lambda: True

        with (
            patch("app.services.ai_service.urlopen", return_value=StreamingResponse(payload)),
            patch("app.services.ai_service.db.get_setting", return_value="sim"),
        ):
            events = list(service.stream("我头晕", context={"profile": {"name": "张三"}}))

        text = "".join(str(event.get("text") or "") for event in events)
        self.assertEqual(text, "头晕持续多久？")
        self.assertNotIn("内部推理", text)
        self.assertEqual(events[0]["source"], "cloud")

    def test_compact_turn_context_does_not_repeat_policy(self) -> None:
        context = {
            "profile": {"name": "张三", "age": 65, "conditions": "高血压", "allergies": "头孢"},
            "vitals": "体温36.5℃，心率72次/分，血氧98%",
            "transcript": "头晕；半天；未用药",
        }

        prompt = AiService._chat_user_prompt("有点口渴", context)

        self.assertIn("张三", prompt)
        self.assertIn("有点口渴", prompt)
        self.assertLess(len(prompt), 260)
        self.assertNotIn("你是家庭康护场景", prompt)


if __name__ == "__main__":
    unittest.main()
