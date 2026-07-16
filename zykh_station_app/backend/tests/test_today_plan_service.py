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

    def test_default_plan_uses_existing_user_and_cabinet_medicine(self) -> None:
        plans = self.service.list_today_plans()

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].target_user, "张三")
        self.assertEqual(plans[0].medicine_id, "slot-21-amlodipine")
        self.assertEqual(plans[0].medicine, "苯磺酸氨氯地平片")

    def test_plan_crud_keeps_normalized_links_and_does_not_reseed_after_delete(self) -> None:
        default_plan = self.service.list_today_plans()[0]
        created = self.service.create_today_plan(
            TodayPlanCreateRequest(
                time="20:30",
                medicine_id="slot-02-centrum",
                service_user_id="lisi",
                dose="1片",
                status="待执行",
            )
        )
        self.assertEqual(created.target_user, "李四")
        self.assertEqual(created.medicine, "多维元素片")

        updated = self.service.update_today_plan(created.id, TodayPlanUpdateRequest(status="已执行", time="21:00"))
        self.assertEqual(updated.status, "已执行")
        self.assertEqual(updated.time, "21:00")

        self.service.delete_today_plan(created.id)
        self.service.delete_today_plan(default_plan.id)
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


if __name__ == "__main__":
    unittest.main()
