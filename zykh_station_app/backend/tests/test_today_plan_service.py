from __future__ import annotations

import sys
import tempfile
import unittest
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.schemas.records import TodayPlanCreateRequest, TodayPlanUpdateRequest  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class TodayPlanServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "plans.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        self.service = RecordsService()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_default_plans_seed_two_people_with_three_labeled_tasks_each(self) -> None:
        plans = self.service.list_today_plans()

        self.assertEqual(len(plans), 6)
        self.assertEqual(Counter(plan.target_user for plan in plans), {"张三": 3, "李四": 3})
        self.assertEqual(
            {plan.timing_label for plan in plans},
            {"早餐前", "早餐后", "午饭后", "晚饭后", "睡前"},
        )
        self.assertIn("slot-21-amlodipine", {plan.medicine_id for plan in plans})
        self.assertTrue(all(plan.status == "待执行" for plan in plans))

    def test_plan_crud_keeps_normalized_links_and_does_not_reseed_after_delete(self) -> None:
        default_plans = self.service.list_today_plans()
        created = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="20:30",
                timing_label="晚饭后",
                medicine_id="slot-02-centrum",
                service_user_id="lisi",
                dose="1片",
                status="待执行",
            )
        )
        self.assertEqual(created.target_user, "李四")
        self.assertEqual(created.medicine, "多维元素片")
        self.assertEqual(created.timing_label, "晚饭后")

        updated = self.service.update_today_plan(
            created.id,
            TodayPlanUpdateRequest(status="已执行", time="21:00", timing_label="睡前"),
        )
        self.assertEqual(updated.status, "已执行")
        self.assertEqual(updated.time, "21:00")
        self.assertEqual(updated.timing_label, "睡前")

        self.service.delete_today_plan(created.id)
        for plan in default_plans:
            self.service.delete_today_plan(plan.id)
        self.assertEqual(self.service.list_today_plans(), [])

    def test_invalid_user_or_medicine_is_rejected(self) -> None:
        self.service.list_today_plans()
        with self.assertRaisesRegex(ValueError, "药品不存在"):
            self.service.create_today_plan(
                TodayPlanCreateRequest(
                    time="09:00",
                    medicine_id="missing",
                    service_user_id="zhangsan",
                )
            )

    def test_interval_and_weekly_plans_only_appear_on_due_dates(self) -> None:
        self.service.list_today_plans()
        start = date(2026, 7, 16)
        interval = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="09:30",
                medicine_id="slot-02-centrum",
                service_user_id="lisi",
                schedule_type="interval",
                interval_days=2,
                start_date=start.isoformat(),
            )
        )
        weekly = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="21:00",
                medicine_id="slot-08-huoxiang-zhengqi",
                service_user_id="wangwu",
                schedule_type="weekly",
                weekdays=[start.isoweekday()],
                start_date=start.isoformat(),
            )
        )

        due_on_start = {plan.id for plan in self.service.list_today_plans(due_only=True, reference_date=start)}
        due_next_day = {
            plan.id for plan in self.service.list_today_plans(due_only=True, reference_date=start + timedelta(days=1))
        }
        due_two_days_later = {
            plan.id for plan in self.service.list_today_plans(due_only=True, reference_date=start + timedelta(days=2))
        }

        self.assertIn(interval.id, due_on_start)
        self.assertIn(weekly.id, due_on_start)
        self.assertNotIn(interval.id, due_next_day)
        self.assertNotIn(weekly.id, due_next_day)
        self.assertIn(interval.id, due_two_days_later)
        self.assertEqual(interval.frequency_label, "每 2 天")
        self.assertTrue(weekly.frequency_label.startswith("每周"))

    def test_completed_recurring_plan_returns_to_pending_on_next_due_day(self) -> None:
        plan = self.service.list_today_plans(due_only=True)[0]
        completed = self.service.complete_today_plan(plan.id, plan.medicine_id, plan.service_user_id)

        self.assertEqual(completed.status, "已执行")
        tomorrow = date.today() + timedelta(days=1)
        next_day = next(item for item in self.service.list_today_plans(reference_date=tomorrow) if item.id == plan.id)
        self.assertEqual(next_day.status, "待执行")


if __name__ == "__main__":
    unittest.main()
