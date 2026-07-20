from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.repositories.inquiry_repository import InquiryRepository  # noqa: E402
from app.schemas.inquiry import InquirySessionResponse  # noqa: E402


class InquiryRepositoryPresentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch(
            "app.db.settings",
            SimpleNamespace(db_path=Path(self.temp_dir.name) / "station.db"),
        )
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_legacy_technical_failure_is_hidden_when_history_is_read(self) -> None:
        repository = InquiryRepository()
        now = db.now_text()
        repository.save_session(
            InquirySessionResponse(
                session_id="legacy-session",
                user_name="张三",
                stage="symptoms",
                reply="智能问询当前暂不可用。本次不会生成用药候选。",
                source="ai_unavailable",
                next_action="ask",
                created_at=now,
                updated_at=now,
            )
        )
        repository.append_message(
            "legacy-session",
            "assistant",
            "云端连接有些不稳定，已使用规则兜底。",
            "rules_fallback",
        )

        restored = repository.get_session("legacy-session")

        self.assertIsNotNone(restored)
        self.assertEqual(restored.source, "assistant")
        self.assertIn("重新开始问询", restored.reply)
        self.assertNotIn("暂不可用", restored.reply)
        self.assertEqual(restored.messages[0].source, "assistant")
        self.assertIn("重新开始问询", restored.messages[0].content)
        self.assertNotIn("规则", restored.messages[0].content)

    def test_normal_safety_guidance_is_preserved(self) -> None:
        repository = InquiryRepository()
        now = db.now_text()
        guidance = "如果出现胸痛或呼吸困难，请立即联系医生。"
        repository.save_session(
            InquirySessionResponse(
                session_id="safety-session",
                user_name="张三",
                stage="escalated",
                reply=guidance,
                source="safety_rules",
                next_action="escalate",
                created_at=now,
                updated_at=now,
            )
        )

        restored = repository.get_session("safety-session")

        self.assertIsNotNone(restored)
        self.assertEqual(restored.reply, guidance)
        self.assertEqual(restored.source, "safety_rules")


if __name__ == "__main__":
    unittest.main()
