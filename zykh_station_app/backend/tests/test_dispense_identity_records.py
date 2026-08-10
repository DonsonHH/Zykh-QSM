from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

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

    fastapi_stub.APIRouter = _APIRouter
    fastapi_stub.HTTPException = _HTTPException
    sys.modules["fastapi"] = fastapi_stub

from fastapi import HTTPException  # noqa: E402

from app import db  # noqa: E402
from app.repositories.identity_assertion_repository import IdentityAssertionRepository  # noqa: E402
from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.routers.dispense import confirm_dispense, open_cabinet  # noqa: E402
from app.schemas.dispense import DispenseConfirmRequest, DispenseOpenRequest  # noqa: E402
from app.schemas.manual_medication_access import (  # noqa: E402
    AssessManualMedicationCommand,
    ConfirmManualMedicationCommand,
    ManualMedicationAssessment,
)
from app.schemas.medicine import (  # noqa: E402
    MedicineInventoryConfirmationRequest,
    MedicineScanRegisterRequest,
)
from app.schemas.records import TodayPlanCreateRequest  # noqa: E402
from app.services.dispense_service import DispenseError, DispenseService  # noqa: E402
from app.services.manual_dispense_adapter import DispenseServiceManualAdapter  # noqa: E402
from app.services.manual_medication_access_module import ManualMedicationAccessModule  # noqa: E402
from app.services.medicine_service import MedicineService  # noqa: E402
from app.services.medicine_inventory_confirmation import (  # noqa: E402
    MedicineInventoryConfirmationConflictError,
    MedicineInventoryConfirmationModule,
)
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class SuccessfulQsmClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, bool]] = []

    def dispense(
        self,
        slot: str,
        quantity: int,
        dry_run: bool = False,
        operation_id: str = "",
    ) -> dict[str, object]:
        del operation_id
        self.calls.append((slot, quantity, dry_run))
        return {"ok": True, "detail": f"slot={slot} quantity={quantity} dry_run={dry_run}"}


class FailedQsmClient:
    def dispense(
        self,
        slot: str,
        quantity: int,
        dry_run: bool = False,
        operation_id: str = "",
    ) -> dict[str, object]:
        del operation_id
        return {"ok": False, "detail": "mock cabinet failure"}


class UnknownThenReplayQsmClient:
    def __init__(self) -> None:
        self.operation_ids: list[str] = []

    def dispense(
        self,
        slot: str,
        quantity: int,
        dry_run: bool = False,
        operation_id: str = "",
    ) -> dict[str, object]:
        del slot, quantity, dry_run
        self.operation_ids.append(operation_id)
        if len(self.operation_ids) == 1:
            return {
                "ok": False,
                "detail": "response connection closed",
                "result_unknown": True,
                "retry_safe": False,
            }
        return {"ok": True, "detail": "replayed completed operation"}


class ContradictoryUnknownQsmClient:
    def dispense(
        self,
        slot: str,
        quantity: int,
        dry_run: bool = False,
        operation_id: str = "",
    ) -> dict[str, object]:
        del slot, quantity, dry_run, operation_id
        return {
            "ok": True,
            "detail": "gateway could not persist the final result",
            "result_unknown": True,
            "retry_safe": False,
        }


class SameStockAdminUpdateQsmClient:
    def __init__(self, medicine_id: str) -> None:
        self.medicine_id = medicine_id

    def dispense(
        self,
        slot: str,
        quantity: int,
        dry_run: bool = False,
        operation_id: str = "",
    ) -> dict[str, object]:
        del slot, quantity, dry_run, operation_id
        repository = MedicineRepository()
        current = repository.get_by_id(self.medicine_id)
        assert current is not None
        repository.update(self.medicine_id, {"stock": current.stock})
        return {"ok": True, "detail": "cabinet opened while admin saved stock"}


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
        self.qsm = SuccessfulQsmClient()
        self.service = DispenseService(qsm_client=self.qsm, archive_service=self.archive)

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _assess_manual_inventory(
        self,
        medicine_id: str,
        *,
        request_suffix: str,
        service_user_id: str = "li-yeye",
        verification_method: str = "face",
    ) -> tuple[ManualMedicationAccessModule, ManualMedicationAssessment]:
        medicine = MedicineRepository().get_by_id(medicine_id)
        self.assertIsNotNone(medicine)
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id=service_user_id,
            verification_method=verification_method,
            verification_score=0.97,
        )
        module = ManualMedicationAccessModule(
            repository=ManualMedicationAccessRepository(),
            identity_assertions=assertions,
            dispense_adapter=DispenseServiceManualAdapter(self.service),
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id=f"assess-{request_suffix}",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id=service_user_id,
                verification_method=verification_method,
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
            )
        )
        return module, assessment

    @staticmethod
    def _real_dispense_settings() -> SimpleNamespace:
        return SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

    def test_scheduled_dispense_requires_expected_person_and_completes_plan(self) -> None:
        plan = self.records.get_today_plan("plan-demo-wang-amlodipine")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.persona_generation, "senior-demo-v1")
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
        self.assertTrue(result.inventory_confirmation_required)
        self.assertEqual(self.records.get_today_plan(plan.id).status, "已执行")
        refreshed = MedicineRepository().get_by_id(medicine.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.stock, medicine.stock)
        self.assertEqual(refreshed.inventory_state, "UNKNOWN")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, result.record_id)
        saved = self.service.list_records()[0]
        self.assertEqual(saved.target_user_name, plan.target_user)
        self.assertEqual(saved.target_user_type, "registered")
        self.assertEqual(saved.today_plan_id, plan.id)
        self.assertEqual(saved.persona_generation, "senior-demo-v1")

        with self.assertRaisesRegex(DispenseError, "已经处理"):
            self.service.confirm(request, force_dry_run=False)

    def test_plan_transport_unknown_is_explicit_and_replays_one_stable_operation(self) -> None:
        plan = self.records.get_today_plan("plan-demo-wang-amlodipine")
        self.assertIsNotNone(plan)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE today_plans
                SET schedule_type='interval', interval_days=2, start_date=?
                WHERE id=?
                """,
                (date.today().isoformat(), plan.id),
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
        qsm = UnknownThenReplayQsmClient()
        service = DispenseService(qsm_client=qsm, archive_service=self.archive)

        first = service.confirm(request, force_dry_run=False)

        self.assertFalse(first.ok)
        self.assertTrue(first.result_unknown)
        self.assertFalse(first.retry_safe)
        self.assertIn("现场确认", first.message)
        self.assertIn("请勿自动重试", first.message)
        self.assertEqual(self.records.get_today_plan(plan.id).status, "待执行")

        next_day = date.today() + timedelta(days=1)
        class NextDayDate(date):
            @classmethod
            def today(cls):
                return next_day

        with patch("app.services.records_service.date", NextDayDate):
            replay = service.confirm(request, force_dry_run=False)

        self.assertTrue(replay.ok)
        self.assertEqual(len(qsm.operation_ids), 2)
        self.assertTrue(qsm.operation_ids[0])
        self.assertEqual(qsm.operation_ids[0], qsm.operation_ids[1])
        with db.connect() as conn:
            operation = conn.execute(
                """
                SELECT status, last_action_date, dispense_operation_id,
                       dispense_operation_state
                FROM today_plans WHERE id=?
                """,
                (plan.id,),
            ).fetchone()
        self.assertEqual(operation["dispense_operation_id"], qsm.operation_ids[0])
        self.assertEqual(operation["dispense_operation_state"], "complete")
        self.assertEqual(operation["status"], "已执行")
        self.assertEqual(operation["last_action_date"], next_day.isoformat())

    def test_result_unknown_dominates_a_contradictory_qsm_ok_flag(self) -> None:
        plan = self.records.get_today_plan("plan-demo-wang-amlodipine")
        self.assertIsNotNone(plan)
        medicine = MedicineService().get_medicine(plan.medicine_id)
        self.assertIsNotNone(medicine)
        service = DispenseService(
            qsm_client=ContradictoryUnknownQsmClient(),
            archive_service=self.archive,
        )

        result = service.confirm(
            DispenseConfirmRequest(
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
            ),
            force_dry_run=False,
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.result_unknown)
        self.assertFalse(result.retry_safe)
        self.assertEqual(self.records.get_today_plan(plan.id).status, "待执行")

    def test_inquiry_action_request_id_replays_one_stable_board_operation(self) -> None:
        medicine = MedicineService().get_medicine("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        request = DispenseConfirmRequest(
            medicine_id=medicine.id,
            slot=medicine.slot,
            quantity=1,
            reason="AI应急问询方案取药",
            confirmed_safety_notice=True,
            confirm_real_dispense=True,
            target_user_id="li-yeye",
            target_user_name="李爷爷",
            verification_method="inquiry_confirmed",
            expected_review_fingerprint=(
                MedicineKnowledgeRepository.review_fingerprint(medicine)
            ),
            request_id="inquiry-session-001:option-01:0",
        )
        qsm = UnknownThenReplayQsmClient()
        service = DispenseService(qsm_client=qsm, archive_service=self.archive)

        first = service.confirm(request, force_dry_run=False)
        replay = service.confirm(request, force_dry_run=False)

        self.assertTrue(first.result_unknown)
        self.assertTrue(replay.ok)
        self.assertEqual(len(qsm.operation_ids), 2)
        self.assertTrue(qsm.operation_ids[0].startswith("inquiry-"))
        self.assertEqual(qsm.operation_ids[0], qsm.operation_ids[1])

    def test_real_inquiry_without_action_request_id_fails_closed_before_qsm(self) -> None:
        medicine = MedicineService().get_medicine("slot-17-iodophor")
        self.assertIsNotNone(medicine)

        with self.assertRaisesRegex(DispenseError, "稳定动作标识"):
            self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason="AI应急问询方案取药",
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id="li-yeye",
                    target_user_name="李爷爷",
                    verification_method="inquiry_confirmed",
                    expected_review_fingerprint=(
                        MedicineKnowledgeRepository.review_fingerprint(medicine)
                    ),
                ),
                force_dry_run=False,
            )

        self.assertEqual(self.qsm.calls, [])

    def test_archived_person_plan_cannot_reach_qsm(self) -> None:
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
        medicine = MedicineService().get_medicine("slot-21-amlodipine")

        with self.assertRaisesRegex(DispenseError, "身份记录不存在|用药计划不存在"):
            self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason="历史计划取药",
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id="lisi",
                    target_user_name="李四",
                    verification_method="fingerprint",
                    today_plan_id="custom-old-child-plan",
                ),
                force_dry_run=False,
            )

        self.assertEqual(self.qsm.calls, [])
        self.assertEqual(self.service.list_records(), [])

    def test_public_manual_inventory_confirm_fails_closed_before_qsm(self) -> None:
        medicine = MedicineService().get_medicine("slot-17-iodophor")
        self.assertIsNotNone(medicine)

        request = DispenseConfirmRequest(
            medicine_id=medicine.id,
            slot=medicine.slot,
            quantity=1,
            reason="药品页普通库存取药",
            confirmed_safety_notice=True,
            confirm_real_dispense=True,
            target_user_id="li-yeye",
            target_user_name="李爷爷",
            verification_method="face",
        )
        with patch("app.routers.dispense.DispenseService", return_value=self.service):
            with self.assertRaises(HTTPException) as raised:
                confirm_dispense(request)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("身份确认和个人用药安全核查", raised.exception.detail)
        self.assertEqual(self.qsm.calls, [])
        self.assertEqual(self.service.list_records(), [])

    def test_manual_inventory_uses_assess_then_confirm_for_reviewed_prescription(self) -> None:
        before = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(before)
        module, assessment = self._assess_manual_inventory(
            "slot-14-oseltamivir",
            request_suffix="li-oseltamivir",
        )

        self.assertEqual(assessment.check_status, "PASSED")
        self.assertEqual(assessment.dispense_status, "NOT_STARTED")
        self.assertEqual(self.qsm.calls, [])

        with patch(
            "app.services.dispense_service.settings",
            self._real_dispense_settings(),
        ):
            confirmation = ConfirmManualMedicationCommand(
                request_id="confirm-li-oseltamivir",
                safety_check_id=assessment.check_id,
                confirmed_safety_notice=True,
            )
            outcome = module.confirm(confirmation)
            replay = module.confirm(confirmation)

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.dispense_status, "DISPENSED")
        self.assertTrue(outcome.inventory_confirmation_required)
        self.assertTrue(replay.inventory_confirmation_required)
        self.assertEqual(self.qsm.calls, [("14", 1, False)])
        record = self.service.list_records()[0]
        self.assertEqual(record.target_user_id, "li-yeye")
        self.assertEqual(record.target_user_name, "李爷爷")
        refreshed = MedicineRepository().get_by_id(before.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.stock, before.stock - 1)
        self.assertEqual(refreshed.inventory_state, "UNKNOWN")
        self.assertEqual(
            refreshed.last_inventory_dispense_record_id,
            outcome.dispense_record_id,
        )

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
        _module, assessment = self._assess_manual_inventory(
            medicine.id,
            request_suffix="unverified-package",
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PACKAGE_UNVERIFIED"])
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(self.qsm.calls, [])

    def test_unreviewed_inquiry_medicine_is_rejected_before_qsm_dispense(self) -> None:
        medicine = MedicineService().get_medicine("slot-08-huoxiang-zhengqi")
        self.assertIsNotNone(medicine)
        MedicineService().repository.update(
            medicine.id,
            {
                "safety_review_status": "draft",
                "safety_reviewed_by": "",
                "safety_reviewed_at": "",
            },
        )
        calls: list[tuple[str, int, bool]] = []

        def recording_dispense(slot: str, quantity: int, dry_run: bool = False):
            calls.append((slot, quantity, dry_run))
            return {"ok": True, "detail": "unexpected"}

        self.service.qsm_client.dispense = recording_dispense

        with self.assertRaisesRegex(DispenseError, "安全资料尚未完成审核"):
            self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason="AI应急问询方案取药",
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id="li-yeye",
                    target_user_name="李爷爷",
                    verification_method="inquiry_confirmed",
                ),
                force_dry_run=False,
            )

        self.assertEqual(calls, [])

    def test_inquiry_confirmed_dispense_requires_the_displayed_review_fingerprint(self) -> None:
        medicine = MedicineService().get_medicine("slot-12-hydrotalcite")
        self.assertIsNotNone(medicine)
        calls: list[tuple[str, int, bool]] = []

        def recording_dispense(slot: str, quantity: int, dry_run: bool = False):
            calls.append((slot, quantity, dry_run))
            return {"ok": True, "detail": "unexpected"}

        self.service.qsm_client.dispense = recording_dispense

        with self.assertRaisesRegex(DispenseError, "重新核对") as raised:
            self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason="AI应急问询方案取药",
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id="li-yeye",
                    target_user_name="李爷爷",
                    verification_method="inquiry_confirmed",
                ),
                force_dry_run=False,
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(calls, [])

    def test_successful_inquiry_dispense_waits_for_physical_inventory_observation(self) -> None:
        medicine = MedicineService().get_medicine("slot-12-hydrotalcite")
        self.assertIsNotNone(medicine)

        result = self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="AI应急问询方案取药",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="li-yeye",
                target_user_name="李爷爷",
                verification_method="inquiry_confirmed",
                expected_review_fingerprint=(
                    MedicineKnowledgeRepository.review_fingerprint(medicine)
                ),
                request_id="inquiry-success-inventory-observation:option-01:0",
            ),
            force_dry_run=False,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.inventory_confirmation_required)
        refreshed = MedicineRepository().get_by_id(medicine.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.stock, medicine.stock)
        self.assertEqual(refreshed.inventory_state, "UNKNOWN")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, result.record_id)

    def test_same_value_admin_stock_update_wins_over_the_in_flight_observation(self) -> None:
        medicine = MedicineService().get_medicine("slot-12-hydrotalcite")
        self.assertIsNotNone(medicine)
        service = DispenseService(
            qsm_client=SameStockAdminUpdateQsmClient(medicine.id),
            archive_service=self.archive,
        )

        result = service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="AI应急问询方案取药",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="li-yeye",
                target_user_name="李爷爷",
                verification_method="inquiry_confirmed",
                expected_review_fingerprint=(
                    MedicineKnowledgeRepository.review_fingerprint(medicine)
                ),
                request_id="inquiry-success-concurrent-inventory:option-01:0",
            ),
            force_dry_run=False,
        )

        self.assertTrue(result.ok)
        self.assertFalse(result.inventory_confirmation_required)
        self.assertIn("请勿重复开柜", result.message)
        refreshed = MedicineRepository().get_by_id(medicine.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.stock, medicine.stock)
        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, "")
        with self.assertRaises(MedicineInventoryConfirmationConflictError):
            MedicineInventoryConfirmationModule().confirm(
                medicine.id,
                MedicineInventoryConfirmationRequest(
                    request_id="inventory-confirm-after-same-stock-admin",
                    dispense_record_id=str(result.record_id),
                    observation="HAS_REMAINING",
                ),
            )

    def test_inquiry_fingerprint_is_rechecked_immediately_before_qsm_dispense(self) -> None:
        medicine = MedicineService().get_medicine("slot-12-hydrotalcite")
        self.assertIsNotNone(medicine)
        replacement = medicine.model_copy(
            update={
                "name": "同仓位重新审核后的其他药品",
                "barcode": "replacement-barcode",
                "safety_reviewed_by": "test-pharmacist-replacement",
                "safety_reviewed_at": "2026-08-08T16:00:00+08:00",
            }
        )
        self.service.medicine_repository.get_by_id = Mock(
            side_effect=[medicine, replacement]
        )
        qsm_calls: list[tuple[str, int, bool]] = []

        def recording_dispense(slot: str, quantity: int, dry_run: bool = False):
            qsm_calls.append((slot, quantity, dry_run))
            return {"ok": True, "detail": "unexpected"}

        self.service.qsm_client.dispense = recording_dispense

        with self.assertRaisesRegex(DispenseError, "身份或安全资料已变化") as raised:
            self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason="AI应急问询方案取药",
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id="li-yeye",
                    target_user_name="李爷爷",
                    verification_method="inquiry_confirmed",
                    expected_review_fingerprint=(
                        MedicineKnowledgeRepository.review_fingerprint(medicine)
                    ),
                    request_id="inquiry-race-review-fingerprint:option-01:0",
                ),
                force_dry_run=False,
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(qsm_calls, [])

    def test_live_stock_is_rechecked_immediately_before_qsm_dispense(self) -> None:
        medicine = MedicineService().get_medicine("slot-12-hydrotalcite")
        self.assertIsNotNone(medicine)
        depleted = medicine.model_copy(update={"stock": 0})
        self.service.medicine_repository.get_by_id = Mock(
            side_effect=[medicine, depleted]
        )
        qsm_calls: list[tuple[str, int, bool]] = []

        def recording_dispense(slot: str, quantity: int, dry_run: bool = False):
            qsm_calls.append((slot, quantity, dry_run))
            return {"ok": True, "detail": "unexpected"}

        self.service.qsm_client.dispense = recording_dispense

        with self.assertRaisesRegex(DispenseError, "库存不足") as raised:
            self.service.confirm(
                DispenseConfirmRequest(
                    medicine_id=medicine.id,
                    slot=medicine.slot,
                    quantity=1,
                    reason="AI应急问询方案取药",
                    confirmed_safety_notice=True,
                    confirm_real_dispense=True,
                    target_user_id="li-yeye",
                    target_user_name="李爷爷",
                    verification_method="inquiry_confirmed",
                    expected_review_fingerprint=(
                        MedicineKnowledgeRepository.review_fingerprint(medicine)
                    ),
                    request_id="inquiry-race-inventory-token:option-01:0",
                ),
                force_dry_run=False,
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(qsm_calls, [])

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
                service_user_id="li-yeye",
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
                service_user_id="wang-nainai",
                dose="按本次处方",
            )
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE service_users SET allergies='青霉素过敏' WHERE id='wang-nainai'"
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

    def test_guest_manual_inventory_assessment_fails_closed_before_qsm(self) -> None:
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(id, name, age, profile, allergies, note, status)
                VALUES ('guest-manual-records', '游客测试', 0, '未登记', '', '', '游客')
                """
            )

        _module, assessment = self._assess_manual_inventory(
            "slot-17-iodophor",
            request_suffix="guest-profile",
            service_user_id="guest-manual-records",
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(self.qsm.calls, [])

    def test_user_records_hide_dry_run_entries(self) -> None:
        medicine = MedicineService().get_medicine("slot-08-huoxiang-zhengqi")
        self.assertIsNotNone(medicine)
        self.service.confirm_debug_dry_run(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="接口调试",
                confirmed_safety_notice=True,
                confirm_real_dispense=False,
                target_user_id="li-yeye",
                target_user_name="李爷爷",
                verification_method="fingerprint",
            )
        )

        self.assertEqual(len(self.service.list_records()), 1)
        self.assertEqual(self.records.get_recent_records(), [])
        self.assertEqual(self.records.get_summary().local_record_count, 0)

    def test_medicine_history_count_includes_successful_confirmation_variants_only(self) -> None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET stock=3 WHERE id='slot-17-iodophor'"
            )
        medicine = MedicineService().get_medicine("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        plan = self.records.create_today_plan(
            TodayPlanCreateRequest(
                time="11:45",
                timing_label="医生确认",
                medicine_id=medicine.id,
                service_user_id="li-yeye",
                dose="外用一次",
            )
        )

        module, assessment = self._assess_manual_inventory(
            medicine.id,
            request_suffix="history-manual",
        )
        self.assertEqual(assessment.check_status, "PASSED")
        with patch(
            "app.services.dispense_service.settings",
            self._real_dispense_settings(),
        ):
            manual = module.confirm(
                ConfirmManualMedicationCommand(
                    request_id="confirm-history-manual",
                    safety_check_id=assessment.check_id,
                    confirmed_safety_notice=True,
                )
            )
        self.assertEqual(manual.dispense_status, "DISPENSED")

        plan_result = self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="今日计划一键取药",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="li-yeye",
                target_user_name="李爷爷",
                verification_method="fingerprint",
                today_plan_id=plan.id,
            ),
            force_dry_run=False,
        )
        self.assertTrue(plan_result.ok)

        inquiry_result = self.service.confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="AI应急问询方案取药",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="li-yeye",
                target_user_name="李爷爷",
                verification_method="inquiry_confirmed",
                expected_review_fingerprint=(
                    MedicineKnowledgeRepository.review_fingerprint(medicine)
                ),
                request_id="inquiry-history-success:option-01:0",
            ),
            force_dry_run=False,
        )
        self.assertTrue(inquiry_result.ok)

        self.service.confirm_debug_dry_run(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="接口演练",
                confirmed_safety_notice=True,
                target_user_id="li-yeye",
                target_user_name="李爷爷",
                verification_method="fingerprint",
            )
        )
        failed = DispenseService(qsm_client=FailedQsmClient(), archive_service=self.archive).confirm(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="开柜失败记录",
                confirmed_safety_notice=True,
                confirm_real_dispense=True,
                target_user_id="li-yeye",
                target_user_name="李爷爷",
                verification_method="inquiry_confirmed",
                expected_review_fingerprint=(
                    MedicineKnowledgeRepository.review_fingerprint(medicine)
                ),
                request_id="inquiry-history-failed:option-01:0",
            ),
            force_dry_run=False,
        )
        self.assertFalse(failed.ok)

        successful = [
            record
            for record in self.service.list_records()
            if not record.dry_run and record.qsm_ok
        ]
        self.assertEqual(len(successful), 3)
        self.assertEqual(
            {record.verification_method for record in successful},
            {"face", "fingerprint", "inquiry_confirmed"},
        )

        refreshed = MedicineService().get_medicine(medicine.id)
        listed = next(item for item in MedicineService().list_medicines().medicines if item.id == medicine.id)
        scanned = MedicineService().register_scan_result(MedicineScanRegisterRequest(barcode=medicine.barcode))
        self.assertEqual(refreshed.dispense_count, 3)
        self.assertEqual(listed.dispense_count, 3)
        self.assertFalse(scanned.created)
        self.assertEqual(scanned.medicine.dispense_count, 3)


if __name__ == "__main__":
    unittest.main()
