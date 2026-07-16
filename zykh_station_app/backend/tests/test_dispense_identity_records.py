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
from app.schemas.dispense import DispenseConfirmRequest  # noqa: E402
from app.services.dispense_service import DispenseError, DispenseService  # noqa: E402
from app.services.medicine_service import MedicineService  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class SuccessfulQsmClient:
    def dispense(self, slot: str, quantity: int, dry_run: bool = False) -> dict[str, object]:
        return {"ok": True, "detail": f"slot={slot} quantity={quantity} dry_run={dry_run}"}


class DispenseIdentityRecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "dispense.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        MedicineService().list_medicines()
        self.records = RecordsService()
        self.service = DispenseService(qsm_client=SuccessfulQsmClient())

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_scheduled_dispense_requires_expected_person_and_completes_plan(self) -> None:
        plan = next(
            item for item in self.records.list_today_plans(due_only=True)
            if item.target_user == "张三"
        )
        medicine = MedicineService().get_medicine(plan.medicine_id)
        self.assertIsNotNone(medicine)
        request = DispenseConfirmRequest(
            medicine_id=medicine.id,
            slot=medicine.slot,
            quantity=1,
            reason="今日计划一键取药",
            confirmed_safety_notice=True,
            confirm_real_dispense=True,
            target_user_id=plan.service_user_id,
            target_user_name=plan.target_user,
            verification_method="fingerprint",
            today_plan_id=plan.id,
        )

        result = self.service.confirm(request, force_dry_run=False)

        self.assertTrue(result.ok)
        self.assertEqual(self.records.get_today_plan(plan.id).status, "已执行")
        saved = self.service.list_records()[0]
        self.assertEqual(saved.target_user_name, plan.target_user)
        self.assertEqual(saved.target_user_type, "registered")
        self.assertEqual(saved.today_plan_id, plan.id)

        with self.assertRaisesRegex(DispenseError, "已经处理"):
            self.service.confirm(request, force_dry_run=False)

    def test_guest_dispense_is_explicitly_labeled_as_guest(self) -> None:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO service_users(id, name, age, profile, allergies, note, status) VALUES (?, ?, 0, '未登记', '', '', '游客')",
                ("guest-test", "游客 0716-2100"),
            )
        medicine = MedicineService().get_medicine("slot-08-huoxiang-zhengqi")
        self.assertIsNotNone(medicine)

        self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="家庭药柜取药确认",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="guest-test",
                target_user_name="错误的前端名称",
                verification_method="face",
            ),
            force_dry_run=False,
        )

        record = self.service.list_records()[0]
        recent = self.records.get_recent_records()[0]
        self.assertEqual(record.target_user_name, "游客 0716-2100")
        self.assertEqual(record.target_user_type, "guest")
        self.assertEqual(recent.target_user, "游客 0716-2100")
        self.assertEqual(recent.title, medicine.name)
        self.assertRegex(recent.time, r"\d{2}-\d{2} \d{2}:\d{2}")
        self.assertEqual(recent.target_user_type, "guest")

    def test_anonymous_face_fallback_is_recorded_as_named_visitor(self) -> None:
        medicine = MedicineService().get_medicine("slot-08-huoxiang-zhengqi")
        self.assertIsNotNone(medicine)

        self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="游客二次确认取药",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="",
                target_user_name="游客（未识别人脸）",
                verification_method="face_guest_confirmed",
            ),
            force_dry_run=False,
        )

        recent = self.records.get_recent_records()[0]
        self.assertEqual(recent.target_user, "游客（未识别人脸）")
        self.assertEqual(recent.target_user_type, "guest")

    def test_user_records_hide_dry_run_entries(self) -> None:
        medicine = MedicineService().get_medicine("slot-08-huoxiang-zhengqi")
        self.assertIsNotNone(medicine)
        self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="接口调试",
                confirmed_safety_notice=True,
                confirm_real_dispense=False,
                target_user_id="zhangsan",
                target_user_name="张三",
                verification_method="fingerprint",
            ),
            force_dry_run=True,
        )

        self.assertEqual(len(self.service.list_records()), 1)
        self.assertEqual(self.records.get_recent_records(), [])
        self.assertEqual(self.records.get_summary().local_record_count, 0)


if __name__ == "__main__":
    unittest.main()
