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

    def test_medication_safety_notices_round_trip_with_the_inquiry_session(self) -> None:
        repository = InquiryRepository()
        now = db.now_text()
        repository.save_session(
            InquirySessionResponse(
                session_id="medication-safety-session",
                user_name="访客",
                stage="result",
                reply="当前仍有一个通过安全核验的候选方案。",
                source="cloud",
                next_action="show_recommendation",
                medication_safety_notices=[
                    {
                        "code": "duplicate_current_medication",
                        "message": (
                            "因你本次已使用含对乙酰氨基酚的药品，为避免重复成分，"
                            "复方感冒灵颗粒未纳入本次候选。"
                        ),
                    }
                ],
                created_at=now,
                updated_at=now,
            )
        )

        restored = repository.get_session("medication-safety-session")

        self.assertIsNotNone(restored)
        self.assertEqual(
            [notice.model_dump() for notice in restored.medication_safety_notices],
            [
                {
                    "code": "duplicate_current_medication",
                    "message": (
                        "因你本次已使用含对乙酰氨基酚的药品，为避免重复成分，"
                        "复方感冒灵颗粒未纳入本次候选。"
                    ),
                }
            ],
        )

    def test_legacy_session_without_medication_notices_defaults_to_empty(self) -> None:
        repository = InquiryRepository()
        now = db.now_text()
        repository.save_session(
            InquirySessionResponse(
                session_id="legacy-without-medication-notices",
                user_name="访客",
                stage="symptoms",
                reply="请描述最明显的不适。",
                source="assistant",
                next_action="ask",
                created_at=now,
                updated_at=now,
            )
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE inquiry_sessions SET extracted_json='{}' WHERE session_id=?",
                ("legacy-without-medication-notices",),
            )

        restored = repository.get_session("legacy-without-medication-notices")

        self.assertIsNotNone(restored)
        self.assertEqual(restored.medication_safety_notices, [])


if __name__ == "__main__":
    unittest.main()
