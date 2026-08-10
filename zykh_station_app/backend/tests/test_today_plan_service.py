from __future__ import annotations

import sys
import tempfile
import unittest
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

    def test_default_plans_seed_exact_2026_08_10_senior_contract(self) -> None:
        plans = {plan.id: plan for plan in self.service.list_today_plans()}
        users = {user.id: user for user in self.service.list_service_users()}

        self.assertEqual(set(users), {"wang-nainai", "li-yeye"})
        self.assertEqual(
            {
                plan_id: (
                    plan.service_user_id,
                    plan.target_user,
                    plan.medicine_id,
                    plan.time,
                    plan.timing_label,
                    plan.dose,
                    plan.status,
                )
                for plan_id, plan in plans.items()
            },
            {
                "plan-demo-wang-amlodipine": (
                    "wang-nainai",
                    "王奶奶",
                    "slot-21-amlodipine",
                    "08:00",
                    "早餐后",
                    "1 片（按既往有效医嘱）",
                    "待执行",
                ),
                "plan-demo-wang-budesonide": (
                    "wang-nainai",
                    "王奶奶",
                    "slot-18-budesonide-nasal",
                    "21:00",
                    "睡前",
                    "每侧鼻孔 1 喷（按既往有效医嘱）",
                    "待执行",
                ),
                "plan-demo-li-lactulose": (
                    "li-yeye",
                    "李爷爷",
                    "slot-06-lactulose",
                    "07:30",
                    "早餐时",
                    "10 毫升（按既往有效医嘱）",
                    "待执行",
                ),
                "plan-demo-li-desloratadine": (
                    "li-yeye",
                    "李爷爷",
                    "slot-23-desloratadine",
                    "20:30",
                    "睡前",
                    "每次 1 粒（按既往有效医嘱）",
                    "待执行",
                ),
            },
        )

    def test_plan_crud_keeps_normalized_links_and_does_not_reseed_after_delete(self) -> None:
        default_plans = self.service.list_today_plans()
        created = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="20:30",
                timing_label="晚饭后",
                medicine_id="slot-02-centrum",
                service_user_id="li-yeye",
                dose="1 片",
                status="待执行",
            )
        )
        self.assertEqual(created.target_user, "李爷爷")
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

    def test_seed_upgrade_preserves_admin_edits_custom_plans_and_completion(self) -> None:
        default_plans = {plan.id: plan for plan in self.service.list_today_plans()}
        completed_plan = default_plans["plan-demo-wang-amlodipine"]
        self.service.update_today_plan(
            completed_plan.id,
            TodayPlanUpdateRequest(time="08:20", dose="管理员确认剂量"),
        )
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
                service_user_id="wang-nainai",
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
        self.assertEqual(plans[completed_plan.id].time, "08:20")
        self.assertEqual(plans[completed_plan.id].dose, "管理员确认剂量")
        self.assertEqual(plans[custom.id].medicine, "藿香正气丸")

    def test_legacy_empty_table_is_repaired_once_without_future_reseeding(self) -> None:
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
        self.assertEqual(
            {plan.id for plan in repaired},
            {
                "plan-demo-wang-amlodipine",
                "plan-demo-wang-budesonide",
                "plan-demo-li-lactulose",
                "plan-demo-li-desloratadine",
            },
        )

        for plan in repaired:
            self.service.delete_today_plan(plan.id)
        self.assertEqual(self.service.list_today_plans(), [])

    def test_default_plans_are_not_reassigned_when_canonical_people_are_missing(self) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM today_plans")
            conn.execute("DELETE FROM service_users")
            conn.executemany(
                """
                INSERT INTO service_users(id, name, age, profile, allergies, note, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("user-dynamic-a", "临时人物甲", 65, "高血压", "头孢过敏", "", "重点关注"),
                    ("user-dynamic-b", "临时人物乙", 61, "家庭成员", "", "", "已登记"),
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

        self.assertEqual(plans, [])

    def test_default_plans_are_not_bound_to_a_different_person_reusing_a_demo_id(self) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM service_users WHERE id='wang-nainai'")
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  allergy_facts_json, safety_profile_revision,
                  safety_profile_updated_at, persona_generation, archived
                ) VALUES (
                  'wang-nainai', '同名 ID 的真实用户', 56, '普通家庭成员', '', '',
                  '已登记', '[]', '[]', '[]', 7, ?, 'real-person-v7', 0
                )
                """,
                (db.now_text(),),
            )

        plans = self.service.list_today_plans()

        self.assertEqual(plans, [])
        with db.connect() as conn:
            stored = conn.execute(
                "SELECT name, persona_generation FROM service_users WHERE id='wang-nainai'"
            ).fetchone()
        self.assertEqual(stored["name"], "同名 ID 的真实用户")
        self.assertEqual(stored["persona_generation"], "real-person-v7")

    def test_legacy_plan_with_unresolved_person_and_medicine_is_quarantined_not_deleted(self) -> None:
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO today_plans(
                  id, time, medicine, target_user, status,
                  medicine_id, service_user_id
                ) VALUES (
                  'legacy-unresolved-plan', '09:15', '历史手工录入药品',
                  '历史手工录入人物', '待执行', '', ''
                )
                """
            )

        db.init_db()

        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, medicine, target_user, medicine_id, service_user_id, archived
                FROM today_plans WHERE id='legacy-unresolved-plan'
                """
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["medicine"], "历史手工录入药品")
        self.assertEqual(row["target_user"], "历史手工录入人物")
        self.assertEqual(row["medicine_id"], "")
        self.assertEqual(row["service_user_id"], "")
        self.assertEqual(row["archived"], 1)
        self.assertNotIn(
            "legacy-unresolved-plan",
            {plan.id for plan in self.service.list_today_plans()},
        )

    def test_archived_person_plans_are_quarantined_and_cannot_be_created(self) -> None:
        self.service.list_today_plans()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(id, name, age, profile, allergies, note, status, archived)
                VALUES ('lisi', '李四', 68, '历史演示人物', '', '', '已归档', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO today_plans(
                  id, time, medicine_id, service_user_id, dose, status,
                  medicine, target_user, updated_at, archived
                ) VALUES (
                  'custom-old-child-plan', '09:10', 'slot-21-amlodipine', 'lisi',
                  '1片', '待执行', '苯磺酸氨氯地平片', '李四', ?, 0
                )
                """,
                (db.now_text(),),
            )

        db.init_db()

        self.assertNotIn(
            "custom-old-child-plan",
            {plan.id for plan in self.service.list_today_plans()},
        )
        with db.connect() as conn:
            stored = conn.execute(
                "SELECT archived FROM today_plans WHERE id='custom-old-child-plan'"
            ).fetchone()
        self.assertEqual(stored["archived"], 1)
        with self.assertRaisesRegex(ValueError, "服务对象不存在"):
            self.service.create_today_plan(
                TodayPlanCreateRequest(
                    time="10:00",
                    medicine_id="slot-21-amlodipine",
                    service_user_id="lisi",
                )
            )

    def test_invalid_user_or_medicine_is_rejected(self) -> None:
        self.service.list_today_plans()
        with self.assertRaisesRegex(ValueError, "药品不存在"):
            self.service.create_today_plan(
                TodayPlanCreateRequest(
                    time="09:00",
                    medicine_id="missing",
                    service_user_id="wang-nainai",
                )
            )

    def test_interval_and_weekly_plans_only_appear_on_due_dates(self) -> None:
        self.service.list_today_plans()
        start = date(2026, 7, 16)
        interval = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="09:30",
                medicine_id="slot-02-centrum",
                service_user_id="li-yeye",
                schedule_type="interval",
                interval_days=2,
                start_date=start.isoformat(),
            )
        )
        weekly = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="21:00",
                medicine_id="slot-08-huoxiang-zhengqi",
                service_user_id="wang-nainai",
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
