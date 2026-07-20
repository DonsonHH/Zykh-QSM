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
            {"早餐时", "早餐后", "午饭后", "晚饭后1至2小时", "睡前"},
        )
        self.assertIn("slot-21-amlodipine", {plan.medicine_id for plan in plans})
        self.assertTrue(all(plan.status == "待执行" for plan in plans))
        users = {user.name: user for user in self.service.list_service_users()}
        self.assertEqual(users["张三"].age, 67)
        self.assertIn("常年性过敏性鼻炎", users["张三"].profile)
        self.assertEqual(users["张三"].allergies, "头孢类药物禁忌")
        self.assertEqual(users["李四"].age, 63)
        self.assertIn("功能性便秘", users["李四"].profile)

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

    def test_seed_upgrade_preserves_existing_plans_and_completion_state(self) -> None:
        default_plans = self.service.list_today_plans()
        completed_plan = default_plans[0]
        self.service.complete_today_plan(
            completed_plan.id,
            completed_plan.medicine_id,
            completed_plan.service_user_id,
        )
        custom = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="16:20",
                timing_label="下午",
                medicine_id="slot-08-huoxiang-zhengqi",
                service_user_id="zhangsan",
                dose="1丸",
                status="待执行",
            )
        )
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE app_settings
                SET value='legacy-family-seed', updated_at=?
                WHERE key='today_plan_seed_version'
                """,
                (db.now_text(),),
            )

        plans = {plan.id: plan for plan in self.service.list_today_plans()}

        self.assertIn(custom.id, plans)
        self.assertEqual(plans[completed_plan.id].status, "已执行")
        self.assertEqual(plans[custom.id].medicine, "藿香正气丸")

    def test_v2_empty_table_is_repaired_once_without_future_reseeding(self) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM today_plans")
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES ('today_plan_seed_version', 'family-demo-v2', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (db.now_text(),),
            )

        repaired = self.service.list_today_plans()
        self.assertEqual(len(repaired), 6)

        for plan in repaired:
            self.service.delete_today_plan(plan.id)
        self.assertEqual(self.service.list_today_plans(), [])

    def test_default_plans_bind_to_existing_people_when_canonical_ids_changed(self) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM today_plans")
            conn.execute("DELETE FROM service_users")
            conn.executemany(
                """
                INSERT INTO service_users(id, name, age, profile, allergies, note, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("user-dynamic-zhangsan", "张三", 65, "高血压", "头孢过敏", "", "重点关注"),
                    ("user-dynamic-zuoyue", "左越", 61, "家庭成员", "", "", "已登记"),
                ],
            )
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES ('today_plan_seed_version', 'family-demo-v3-nondestructive', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (db.now_text(),),
            )

        plans = self.service.list_today_plans()

        self.assertEqual(len(plans), 6)
        self.assertEqual(Counter(plan.target_user for plan in plans), {"张三": 3, "左越": 3})
        self.assertTrue(all(plan.service_user_id.startswith("user-dynamic-") for plan in plans))

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
