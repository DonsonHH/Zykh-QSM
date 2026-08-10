from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

try:
    import fastapi  # noqa: F401
except ModuleNotFoundError:
    fastapi_stub = ModuleType("fastapi")

    class _APIRouter:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def __getattr__(self, _name):
            def route(*args, **kwargs):
                del args, kwargs

                def decorate(function):
                    return function

                return decorate

            return route

    class _HTTPException(Exception):
        def __init__(self, status_code: int, detail: str) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    def _query(default=None, **_kwargs):
        return default

    fastapi_stub.APIRouter = _APIRouter
    fastapi_stub.HTTPException = _HTTPException
    fastapi_stub.Query = _query
    sys.modules["fastapi"] = fastapi_stub

from fastapi import HTTPException  # noqa: E402

from app import db  # noqa: E402
from app.repositories.inquiry_repository import InquiryRepository  # noqa: E402
from app.routers.records import service_user_inquiries, service_users  # noqa: E402
from app.schemas.inquiry import InquirySessionResponse  # noqa: E402
from app.schemas.records import ServiceUserCreateRequest, ServiceUserUpdateRequest  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class ServiceUserInquiryHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch(
            "app.db.settings",
            SimpleNamespace(db_path=Path(self.temp_dir.name) / "station.db"),
        )
        self.db_patch.start()
        db.init_db()
        self.records = RecordsService()
        self.inquiries = InquiryRepository()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _save_inquiry(
        self,
        *,
        session_id: str,
        user_id: str,
        user_name: str,
        updated_at: str,
    ) -> None:
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id=session_id,
                user_id=user_id,
                user_name=user_name,
                stage="result",
                reply="问询完成",
                extracted_information={"case_summary": f"病例 {session_id}"},
                risk_level="low",
                next_action="complete",
                title=f"问询 {session_id}",
                created_at=updated_at,
                updated_at=updated_at,
            )
        )

    def test_archived_user_with_no_inquiries_is_hidden_but_explicitly_readable(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="归档测试人物")
        )
        self.records.update_service_user(
            user.id,
            ServiceUserUpdateRequest(archived=True),
        )

        listed = service_users()
        history = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        )

        self.assertNotIn(user.id, {item.id for item in listed.users})
        self.assertEqual(
            history.model_dump(mode="json"),
            {
                "ok": True,
                "user_id": user.id,
                "inquiries": [],
                "next_cursor": None,
            },
        )

    def test_limit_and_cursor_page_without_duplicates(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="分页人物")
        )
        expected_session_ids = [
            f"history-page-{index:02d}"
            for index in reversed(range(41))
        ]
        for index in range(41):
            self._save_inquiry(
                session_id=f"history-page-{index:02d}",
                user_id=user.id,
                user_name=user.name,
                updated_at=f"2026-08-10 {10 + index // 60:02d}:{index % 60:02d}:00",
            )

        actual_session_ids: list[str] = []
        cursor = None
        page_sizes: list[int] = []
        while True:
            page = service_user_inquiries(user.id, limit=5, cursor=cursor)
            page_sizes.append(len(page.inquiries))
            actual_session_ids.extend(item.session_id for item in page.inquiries)
            cursor = page.next_cursor
            if cursor is None:
                break

        self.assertEqual(page_sizes, [5, 5, 5, 5, 5, 5, 5, 5, 1])
        self.assertEqual(actual_session_ids, expected_session_ids)
        self.assertEqual(len(actual_session_ids), len(set(actual_session_ids)))

    def test_rejects_foreign_cursor_and_out_of_range_limit(self) -> None:
        target = self.records.create_service_user(
            ServiceUserCreateRequest(name="游标目标人物")
        )
        other = self.records.create_service_user(
            ServiceUserCreateRequest(name="游标隔离人物")
        )
        self._save_inquiry(
            session_id="target-cursor-session",
            user_id=target.id,
            user_name=target.name,
            updated_at="2026-08-10 11:00:00",
        )
        self._save_inquiry(
            session_id="foreign-cursor-session",
            user_id=other.id,
            user_name=other.name,
            updated_at="2026-08-10 11:01:00",
        )

        for limit, cursor in (
            (5, "foreign-cursor-session"),
            (0, None),
            (21, None),
        ):
            with self.subTest(limit=limit, cursor=cursor):
                with self.assertRaises(HTTPException) as raised:
                    service_user_inquiries(target.id, limit=limit, cursor=cursor)
                self.assertEqual(raised.exception.status_code, 400)

    def test_projection_is_user_scoped_and_does_not_expose_conversation_internals(self) -> None:
        target = self.records.create_service_user(
            ServiceUserCreateRequest(name="历史投影人物")
        )
        other = self.records.create_service_user(
            ServiceUserCreateRequest(name="隔离人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-target-001",
                user_id=target.id,
                user_name=target.name,
                stage="result",
                reply="SECRET PROMPT: 不得返回这一字段",
                source="debug-secret",
                reasoning_summary="SECRET REASONING: 不得返回备用推理",
                extracted_information={
                    "case_summary": "",
                    "symptoms_text": "咳嗽两天，未见高热",
                },
                risk_level="medium",
                next_action="complete",
                can_view_medicines=True,
                selected_option_id="option-1",
                treatment_options=[
                    {
                        "option_id": "option-1",
                        "label": "咳嗽护理方案",
                        "when": "用户确认后",
                        "medicines": [
                            {
                                "id": "medicine-cough",
                                "name": "蜜炼川贝枇杷膏",
                                "category": "止咳药",
                                "slot": "6",
                                "stock": 2,
                                "unit": "瓶",
                                "safety_note": "按说明书使用",
                            }
                        ],
                    }
                ],
                action_status="complete",
                action_items=[
                    {
                        "medicine_name": "蜜炼川贝枇杷膏",
                        "ok": True,
                    }
                ],
                title="咳嗽复查",
                created_at="2026-08-10 09:00:00",
                updated_at="2026-08-10 09:05:00",
            )
        )
        self.inquiries.append_message(
            "history-target-001",
            "user",
            "SECRET MESSAGE: 不得返回完整对话",
            source="debug",
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-other-001",
                user_id=other.id,
                user_name=other.name,
                stage="result",
                reply="另一人物的回复",
                extracted_information={"case_summary": "另一人物的病例"},
                risk_level="low",
                next_action="complete",
                title="另一人物问询",
                created_at="2026-08-10 10:00:00",
                updated_at="2026-08-10 10:05:00",
            )
        )

        history = service_user_inquiries(target.id, limit=20, cursor=None)

        self.assertEqual(
            history.model_dump(mode="json"),
            {
                "ok": True,
                "user_id": target.id,
                "inquiries": [
                    {
                        "session_id": "history-target-001",
                        "happened_at": "2026-08-10 09:05:00",
                        "title": "咳嗽复查",
                        "case_summary": "咳嗽两天，未见高热",
                        "risk_level": "medium",
                        "risk_label": "中风险",
                        "outcome": "已完成用户确认的取药流程",
                        "final_medicine_summary": "蜜炼川贝枇杷膏",
                    }
                ],
                "next_cursor": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
