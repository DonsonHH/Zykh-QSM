from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.routers.dispense import open_cabinet  # noqa: E402
from app.schemas.dispense import DispenseConfirmRequest, DispenseOpenRequest  # noqa: E402
from app.schemas.medicine import MedicineScanRegisterRequest  # noqa: E402
from app.schemas.records import TodayPlanCreateRequest  # noqa: E402
from app.services.dispense_service import DispenseError, DispenseService  # noqa: E402
from app.services.medicine_service import MedicineService  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class SuccessfulQsmClient:
    def dispense(self, slot: str, quantity: int, dry_run: bool = False) -> dict[str, object]:
        return {"ok": True, "detail": f"slot={slot} quantity={quantity} dry_run={dry_run}"}


class FailedQsmClient:
    def dispense(self, slot: str, quantity: int, dry_run: bool = False) -> dict[str, object]:
        return {"ok": False, "detail": "mock cabinet failure"}


class RecordingArchiveService:
    def __init__(self) -> None:
        self.records = []

    def capture_for_record(self, record) -> dict[str, object]:
        self.records.append(record)
        return {"ok": True, "status": "captured"}


class DispenseIdentityRecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "dispense.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        MedicineService().list_medicines()
        self.records = RecordsService()
        self.archive = RecordingArchiveService()
        self.service = DispenseService(qsm_client=SuccessfulQsmClient(), archive_service=self.archive)

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

    def test_manual_dispense_rejects_pending_expired_and_prescription_inventory(self) -> None:
        blocked = (
            ("slot-15-mupirocin", "已过有效期"),
            ("slot-14-oseltamivir", "处方或既往用药计划"),
        )

        for medicine_id, message in blocked:
            medicine = MedicineService().get_medicine(medicine_id)
            self.assertIsNotNone(medicine)
            request = DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="药品页手动取药",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="zhangsan",
                target_user_name="张三",
                verification_method="face",
            )

            with self.subTest(medicine_id=medicine_id):
                with self.assertRaisesRegex(DispenseError, message):
                    self.service.confirm(request, force_dry_run=False)

    def test_cloud_guidance_cannot_unlock_an_unverified_package(self) -> None:
        repository = MedicineService().repository
        scanned = repository.create_from_scan(
            barcode="unverified-package-001",
            name="待核验扫码药品",
            hardware_slot=24,
        )
        repository.update(
            scanned.id,
            {"guidance_source": "cloud_ai", "guidance_review_required": True},
        )
        medicine = MedicineService().get_medicine(scanned.id)
        self.assertIsNotNone(medicine)
        self.assertFalse(medicine.package_verified)
        request = DispenseConfirmRequest(
            medicine_id=medicine.id,
            slot=medicine.slot,
            quantity=1,
            reason="药品页手动取药",
            confirmed_safety_notice=True,
            confirm_real_dispense=True,
            target_user_id="zhangsan",
            target_user_name="张三",
            verification_method="face",
        )

        with self.assertRaisesRegex(DispenseError, "包装规格尚未人工核验"):
            self.service.confirm(request, force_dry_run=False)

    def test_public_raw_open_endpoint_is_not_an_authorized_cabinet_path(self) -> None:
        with patch("app.routers.dispense.DispenseService") as service_class:
            with self.assertRaises(HTTPException) as raised:
                open_cabinet(DispenseOpenRequest(slot=8, confirmed_open=True))

        self.assertEqual(raised.exception.status_code, 403)
        service_class.assert_not_called()

    def test_doctor_confirmed_plan_unlocks_prescription_item(self) -> None:
        plan = self.records.create_today_plan(
            TodayPlanCreateRequest(
                time="10:00",
                timing_label="医生确认",
                medicine_id="slot-14-oseltamivir",
                service_user_id="zhangsan",
                dose="按本次处方",
            )
        )
        medicine = MedicineService().get_medicine(plan.medicine_id)
        self.assertIsNotNone(medicine)

        result = self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="远程医生确认后的用药计划",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id=plan.service_user_id,
                target_user_name=plan.target_user,
                verification_method="fingerprint",
                today_plan_id=plan.id,
            ),
            force_dry_run=False,
        )

        self.assertTrue(result.ok)
        self.assertEqual(self.records.get_today_plan(plan.id).status, "已执行")

    def test_prescription_plan_still_rejects_registered_allergy_conflict(self) -> None:
        plan = self.records.create_today_plan(
            TodayPlanCreateRequest(
                time="10:30",
                timing_label="医生确认",
                medicine_id="slot-04-amoxicillin",
                service_user_id="zhangsan",
                dose="按本次处方",
            )
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE service_users SET allergies='青霉素过敏' WHERE id='zhangsan'"
            )
        medicine = MedicineService().get_medicine(plan.medicine_id)
        self.assertIsNotNone(medicine)

        with self.assertRaisesRegex(DispenseError, "青霉素过敏"):
            self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason="远程医生确认后的用药计划",
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id=plan.service_user_id,
                    target_user_name=plan.target_user,
                    verification_method="fingerprint",
                    today_plan_id=plan.id,
                ),
                force_dry_run=False,
            )

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
                archive_identity_snapshot=True,
            ),
            force_dry_run=False,
        )

        recent = self.records.get_recent_records()[0]
        self.assertEqual(recent.target_user, "游客（未识别人脸）")
        self.assertEqual(recent.target_user_type, "guest")
        self.assertEqual(len(self.archive.records), 1)
        self.assertEqual(self.archive.records[0].target_user_name, "游客（未识别人脸）")

    def test_registered_dispense_does_not_archive_identity_snapshot(self) -> None:
        medicine = MedicineService().get_medicine("slot-08-huoxiang-zhengqi")
        self.assertIsNotNone(medicine)

        self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="登记成员取药",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="zhangsan",
                target_user_name="张三",
                verification_method="face",
                archive_identity_snapshot=True,
            ),
            force_dry_run=False,
        )

        self.assertEqual(self.archive.records, [])

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

    def test_medicine_history_count_includes_successful_confirmation_variants_only(self) -> None:
        medicine = MedicineService().get_medicine("slot-08-huoxiang-zhengqi")
        self.assertIsNotNone(medicine)
        plan = self.records.create_today_plan(
            TodayPlanCreateRequest(
                time="11:45",
                timing_label="医生确认",
                medicine_id=medicine.id,
                service_user_id="zhangsan",
                dose="1丸",
            )
        )
        entry_modes = (
            ("药品页手动取药", "face", ""),
            ("今日计划一键取药", "fingerprint", plan.id),
            ("AI应急问询方案取药", "inquiry_confirmed", ""),
        )

        for reason, verification_method, today_plan_id in entry_modes:
            result = self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason=reason,
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id="zhangsan",
                    target_user_name="张三",
                    verification_method=verification_method,
                    today_plan_id=today_plan_id,
                ),
                force_dry_run=False,
            )
            self.assertTrue(result.ok)

        self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="接口演练",
                confirmed_safety_notice=True,
                target_user_id="zhangsan",
                target_user_name="张三",
                verification_method="fingerprint",
            ),
            force_dry_run=True,
        )
        failed = DispenseService(qsm_client=FailedQsmClient(), archive_service=self.archive).confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="开柜失败记录",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="zhangsan",
                target_user_name="张三",
                verification_method="face",
            ),
            force_dry_run=False,
        )
        self.assertFalse(failed.ok)

        refreshed = MedicineService().get_medicine(medicine.id)
        listed = next(item for item in MedicineService().list_medicines().medicines if item.id == medicine.id)
        scanned = MedicineService().register_scan_result(MedicineScanRegisterRequest(barcode=medicine.barcode))
        self.assertEqual(refreshed.dispense_count, 3)
        self.assertEqual(listed.dispense_count, 3)
        self.assertFalse(scanned.created)
        self.assertEqual(scanned.medicine.dispense_count, 3)


if __name__ == "__main__":
    unittest.main()
