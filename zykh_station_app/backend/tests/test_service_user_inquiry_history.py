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
        with db.connect() as conn:
            person = conn.execute(
                "SELECT persona_generation FROM service_users WHERE id=?",
                (user_id,),
            ).fetchone()
        persona_generation = str(person["persona_generation"] or "") if person else ""
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id=session_id,
                user_id=user_id,
                persona_generation=persona_generation,
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
                persona_generation=target.persona_generation,
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
                persona_generation=other.persona_generation,
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
                        "risk_reasons": [],
                        "outcome": "已完成用户确认的取药流程",
                        "no_medicine_reason": "",
                        "final_medicine_summary": "蜜炼川贝枇杷膏",
                    }
                ],
                "next_cursor": None,
            },
        )

    def test_high_risk_history_explains_the_safety_gate_without_exposing_internal_text(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="高风险解释人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-high-risk-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="escalated",
                reply="SECRET AI REPLY: 不得作为历史解释",
                reasoning_summary="SECRET REASONING: 不得作为历史解释",
                extracted_information={"case_summary": "黑便并伴有明显头晕"},
                risk_level="high",
                risk_reasons=["出现呕血、黑便或便血", "出现呕血、黑便或便血"],
                next_action="escalate",
                title="消化道出血风险核验",
                created_at="2026-08-10 12:00:00",
                updated_at="2026-08-10 12:05:00",
            )
        )
        self.inquiries.append_message(
            "history-high-risk-001",
            "system",
            "SECRET SYSTEM PROMPT: 不得返回",
            source="debug",
        )

        inquiry = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0]
        public_summary = inquiry.model_dump(mode="json")

        self.assertEqual(public_summary["risk_reasons"], ["出现呕血、黑便或便血"])
        self.assertEqual(
            public_summary["no_medicine_reason"],
            "检测到高风险信号，安全规则不允许展示候选药品",
        )
        self.assertEqual(public_summary["outcome"], "已建议联系医生或现场协助人员")
        self.assertNotIn("reply", public_summary)
        self.assertNotIn("reasoning_summary", public_summary)
        self.assertNotIn("messages", public_summary)
        self.assertNotIn("SECRET", str(public_summary))

    def test_history_explains_when_all_relevant_candidates_failed_safety_checks(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="候选冲突人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-all-blocked-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="result",
                reply="安全核验未通过",
                extracted_information={"case_summary": "发热伴头痛"},
                risk_level="medium",
                risk_reasons=["未触发硬性危险信号"],
                medication_safety_notices=[
                    {"code": "allergy_conflict", "message": "SECRET NOTICE DETAIL"}
                ],
                next_action="complete",
                title="发热问询",
                created_at="2026-08-10 12:10:00",
                updated_at="2026-08-10 12:15:00",
            )
        )

        public_summary = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0].model_dump(mode="json")

        self.assertEqual(
            public_summary["no_medicine_reason"],
            "相关候选药品均因已用药、过敏或既往情况冲突而未通过安全核验",
        )
        self.assertEqual(public_summary["outcome"], "未提供候选药品")
        self.assertNotIn("SECRET NOTICE DETAIL", str(public_summary))

    def test_history_does_not_mislabel_a_rejected_combination_as_a_profile_conflict(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="组合核验人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-combination-blocked-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="result",
                reply="方案未通过核验",
                extracted_information={"case_summary": "腹泻伴腹部不适"},
                risk_level="medium",
                risk_reasons=["未触发硬性危险信号"],
                medication_safety_notices=[
                    {"code": "combination_not_approved", "message": "受控组合未命中"}
                ],
                next_action="complete",
                title="腹泻问询",
                created_at="2026-08-10 12:16:00",
                updated_at="2026-08-10 12:17:00",
            )
        )

        public_summary = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0].model_dump(mode="json")

        self.assertEqual(
            public_summary["no_medicine_reason"],
            "候选方案未通过用药安全或受控组合核验",
        )
        self.assertNotIn("过敏或既往情况冲突", public_summary["no_medicine_reason"])

    def test_history_marks_a_matching_failure_as_retryable_from_landed_state(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="匹配重试人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-ranking-retry-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="clarification",
                reply="SECRET PROVIDER ERROR: 不得返回",
                source="cloud-provider-debug",
                reasoning_summary="SECRET MODEL TRACE",
                model_action_intent="ask",
                action_reason="药品匹配暂未完成，可在同一会话中重试。",
                extracted_information={
                    "case_summary": "轻微咳嗽",
                    "symptom_collection_complete": True,
                },
                risk_level="low",
                risk_reasons=["未触发硬性危险信号"],
                next_action="ask",
                title="咳嗽问询",
                created_at="2026-08-10 12:20:00",
                updated_at="2026-08-10 12:25:00",
            )
        )

        public_summary = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0].model_dump(mode="json")

        self.assertEqual(public_summary["outcome"], "药品匹配可重试")
        self.assertEqual(
            public_summary["no_medicine_reason"],
            "药品匹配服务未稳定返回结果，可在同一会话中重试",
        )
        self.assertNotIn("SECRET", str(public_summary))
        self.assertNotIn("cloud-provider-debug", str(public_summary))

    def test_history_explains_the_basic_care_outcome_when_no_candidate_matches(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="基础护理人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-basic-care-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="result",
                reply="SECRET NATURAL-LANGUAGE FALLBACK",
                extracted_information={"case_summary": "轻微局部不适"},
                risk_level="low",
                risk_reasons=["未触发硬性危险信号"],
                next_action="complete",
                title="局部不适问询",
                created_at="2026-08-10 12:30:00",
                updated_at="2026-08-10 12:35:00",
            )
        )

        public_summary = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0].model_dump(mode="json")

        self.assertEqual(public_summary["outcome"], "建议基础护理和观察")
        self.assertEqual(
            public_summary["no_medicine_reason"],
            "未找到与当前症状相关且通过核验的候选药品",
        )
        self.assertNotIn("SECRET", str(public_summary))

    def test_history_distinguishes_insufficient_symptom_evidence_from_basic_care(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="信息不足人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-insufficient-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="result",
                reply="需要补充测量后重新问询",
                model_action_intent="end",
                action_reason="症状追问已达上限，但关键证据仍不足。",
                extracted_information={"case_summary": "症状描述不完整"},
                risk_level="medium",
                risk_reasons=["关键症状信息不足"],
                next_action="complete",
                title="症状核验",
                created_at="2026-08-10 12:40:00",
                updated_at="2026-08-10 12:45:00",
            )
        )

        public_summary = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0].model_dump(mode="json")

        self.assertEqual(public_summary["outcome"], "信息不足，未提供候选药品")
        self.assertEqual(
            public_summary["no_medicine_reason"],
            "关键症状信息不足，需要补充信息或测量后重新问询",
        )

    def test_history_distinguishes_a_landed_clinical_escalation_from_basic_care(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="人工复核人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-clinical-escalation-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="result",
                reply="SECRET CLINICAL MODEL EXPLANATION",
                model_action_intent="escalate",
                extracted_information={"case_summary": "症状需进一步确认"},
                risk_level="medium",
                risk_reasons=["需要进一步临床确认"],
                next_action="escalate",
                title="进一步核验",
                created_at="2026-08-10 13:00:00",
                updated_at="2026-08-10 13:05:00",
            )
        )

        public_summary = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0].model_dump(mode="json")

        self.assertEqual(public_summary["outcome"], "建议医生或现场人员进一步确认")
        self.assertEqual(
            public_summary["no_medicine_reason"],
            "当前结论需要医生或现场人员进一步确认，本次未展示候选药品",
        )
        self.assertNotIn("SECRET", str(public_summary))

    def test_history_marks_an_unknown_cabinet_result_for_on_site_confirmation(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="开柜待确认人物")
        )
        self.inquiries.save_session(
            InquirySessionResponse(
                session_id="history-result-unknown-001",
                user_id=user.id,
                persona_generation=user.persona_generation,
                user_name=user.name,
                stage="result",
                reply="SECRET QSM ERROR DETAIL",
                action_message="SECRET SERIAL TRACE",
                extracted_information={"case_summary": "低风险对症处理"},
                risk_level="low",
                risk_reasons=["未触发硬性危险信号"],
                next_action="complete",
                can_view_medicines=True,
                action_status="failed",
                action_items=[
                    {
                        "medicine_id": "slot-01-test",
                        "medicine_name": "测试药品",
                        "slot": "1",
                        "ok": False,
                        "result_unknown": True,
                        "message": "SECRET HARDWARE MESSAGE",
                    }
                ],
                title="开柜结果核验",
                created_at="2026-08-10 13:10:00",
                updated_at="2026-08-10 13:15:00",
            )
        )

        public_summary = service_user_inquiries(
            user.id,
            limit=20,
            cursor=None,
        ).inquiries[0].model_dump(mode="json")

        self.assertEqual(public_summary["risk_label"], "核验完成")
        self.assertEqual(public_summary["outcome"], "分类柜亮灯结果待现场确认")
        self.assertEqual(
            public_summary["no_medicine_reason"],
            "亮灯结果未知，请现场核对指示灯和药品，勿重复执行",
        )
        self.assertNotIn("SECRET", str(public_summary))

    def test_history_explains_failed_and_partial_cabinet_actions_from_status_only(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="开柜未完成人物")
        )
        for session_id, status, updated_at, items in (
            (
                "history-action-failed-001",
                "failed",
                "2026-08-10 13:20:00",
                [{"ok": False, "message": "SECRET FAILED DETAIL"}],
            ),
            (
                "history-action-partial-001",
                "partial",
                "2026-08-10 13:21:00",
                [
                    {"ok": True, "medicine_name": "已完成药品"},
                    {"ok": False, "message": "SECRET PARTIAL DETAIL"},
                ],
            ),
        ):
            self.inquiries.save_session(
                InquirySessionResponse(
                    session_id=session_id,
                    user_id=user.id,
                    persona_generation=user.persona_generation,
                    user_name=user.name,
                    stage="result",
                    reply="SECRET QSM REPLY",
                    action_message="SECRET QSM ACTION MESSAGE",
                    extracted_information={"case_summary": "低风险对症处理"},
                    risk_level="low",
                    risk_reasons=["未触发硬性危险信号"],
                    next_action="complete",
                    can_view_medicines=True,
                    action_status=status,
                    action_items=items,
                    title="开柜执行核验",
                    created_at="2026-08-10 13:19:00",
                    updated_at=updated_at,
                )
            )

        history = service_user_inquiries(user.id, limit=20, cursor=None)
        summaries = {
            item.session_id: item.model_dump(mode="json")
            for item in history.inquiries
        }

        self.assertEqual(
            summaries["history-action-failed-001"]["outcome"],
            "分类柜亮灯未完成",
        )
        self.assertEqual(
            summaries["history-action-failed-001"]["no_medicine_reason"],
            "分类柜亮灯执行失败，本次取药未完成",
        )
        self.assertEqual(
            summaries["history-action-partial-001"]["outcome"],
            "部分分类柜已完成亮灯，其余步骤未完成",
        )
        self.assertEqual(
            summaries["history-action-partial-001"]["no_medicine_reason"],
            "取药方案仅部分完成，请现场核对未完成的亮灯步骤",
        )
        self.assertNotIn("SECRET", str(summaries))

    def test_active_user_history_is_scoped_to_the_current_persona_generation(self) -> None:
        user = self.records.create_service_user(
            ServiceUserCreateRequest(name="代次隔离人物")
        )
        for session_id, generation, updated_at in (
            ("history-generation-current-001", user.persona_generation, "2026-08-10 14:00:00"),
            ("history-generation-old-001", "persona-old-generation", "2026-08-10 14:01:00"),
            ("history-generation-legacy-001", "", "2026-08-10 14:02:00"),
        ):
            self.inquiries.save_session(
                InquirySessionResponse(
                    session_id=session_id,
                    user_id=user.id,
                    persona_generation=generation,
                    user_name=user.name,
                    stage="result",
                    reply="问询完成",
                    extracted_information={"case_summary": session_id},
                    risk_level="low",
                    next_action="complete",
                    title=session_id,
                    created_at=updated_at,
                    updated_at=updated_at,
                )
            )

        history = service_user_inquiries(user.id, limit=20, cursor=None)

        self.assertEqual(
            [item.session_id for item in history.inquiries],
            ["history-generation-current-001"],
        )
        with self.assertRaises(HTTPException) as raised:
            service_user_inquiries(
                user.id,
                limit=20,
                cursor="history-generation-old-001",
            )
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
