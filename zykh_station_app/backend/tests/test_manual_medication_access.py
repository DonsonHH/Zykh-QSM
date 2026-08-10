from __future__ import annotations

import tempfile
import threading
import unittest
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db
from app.repositories.medicine_repository import MedicineRepository
from app.services.medicine_service import MedicineService
from app.services.records_service import RecordsService
from app.schemas.records import TodayPlanUpdateRequest


class ManualMedicationAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "manual-medication-access.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        MedicineService().list_medicines()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _manual_execution_command(
        *,
        medicine_id: str,
        operation_id: str,
        expected_stock: int,
    ):
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.schemas.manual_medication_access import ManualDispenseExecutionCommand

        medicine = MedicineRepository().get_by_id(medicine_id)
        person = ManualMedicationAccessRepository().get_person("li-yeye")
        if medicine is None or person is None:
            raise AssertionError("manual execution test fixture is incomplete")
        assertion = IdentityAssertionRepository().issue(
            service_user_id=person.service_user_id,
            verification_method="face",
        )
        return ManualDispenseExecutionCommand(
            qsm_operation_id=operation_id,
            medicine_id=medicine.id,
            medicine_name=medicine.name,
            slot=medicine.slot,
            quantity=1,
            service_user_id=person.service_user_id,
            service_user_name=person.name,
            verification_method="face",
            verification_assertion_id=assertion.assertion_id,
            expected_persona_generation=person.persona_generation,
            expected_safety_profile_revision=person.safety_profile_revision,
            expected_person_safety_fingerprint=person.safety_fingerprint(),
            expected_review_fingerprint=medicine.review_fingerprint,
            expected_hardware_slot=medicine.hardware_slot,
            expected_stock=expected_stock,
            expected_expire_date=medicine.expire_date,
        )

    def test_fresh_station_uses_new_personas_and_exact_demo_plans(self) -> None:
        records = RecordsService()

        users = {user.id: user for user in records.list_service_users()}
        plans = {plan.id: plan for plan in records.list_today_plans()}

        self.assertEqual(set(users), {"wang-nainai", "li-yeye"})
        self.assertEqual(users["wang-nainai"].persona_generation, "senior-demo-v1")
        self.assertEqual(
            {item["concept_code"] for item in users["wang-nainai"].medical_conditions},
            {"hypertension", "allergic_rhinitis", "peptic_ulcer"},
        )
        self.assertEqual(users["li-yeye"].persona_generation, "senior-demo-v1")
        self.assertEqual(
            {item["concept_code"] for item in users["li-yeye"].medical_conditions},
            {"diabetes", "functional_constipation", "allergic_rhinitis"},
        )
        self.assertEqual(
            {
                plan_id: (
                    plan.service_user_id,
                    plan.medicine_id,
                    plan.time,
                    plan.timing_label,
                    plan.dose,
                )
                for plan_id, plan in plans.items()
            },
            {
                "plan-demo-wang-amlodipine": (
                    "wang-nainai",
                    "slot-21-amlodipine",
                    "08:00",
                    "早餐后",
                    "1 片（按既往有效医嘱）",
                ),
                "plan-demo-wang-budesonide": (
                    "wang-nainai",
                    "slot-18-budesonide-nasal",
                    "21:00",
                    "睡前",
                    "每侧鼻孔 1 喷（按既往有效医嘱）",
                ),
                "plan-demo-li-lactulose": (
                    "li-yeye",
                    "slot-06-lactulose",
                    "07:30",
                    "早餐时",
                    "10 毫升（按既往有效医嘱）",
                ),
                "plan-demo-li-desloratadine": (
                    "li-yeye",
                    "slot-23-desloratadine",
                    "20:30",
                    "睡前",
                    "每次 1 粒（按既往有效医嘱）",
                ),
            },
        )

    def test_seed_upgrade_does_not_overwrite_an_admin_edited_demo_plan(self) -> None:
        records = RecordsService()
        records.list_today_plans()
        records.update_today_plan(
            "plan-demo-wang-amlodipine",
            TodayPlanUpdateRequest(time="08:20", dose="管理员确认剂量"),
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE app_settings SET value='older-seed' WHERE key='today_plan_seed_version'"
            )

        plans = {plan.id: plan for plan in records.list_today_plans()}

        self.assertEqual(plans["plan-demo-wang-amlodipine"].time, "08:20")
        self.assertEqual(plans["plan-demo-wang-amlodipine"].dose, "管理员确认剂量")

    def test_assess_blocks_wang_ibuprofen_idempotently_without_qsm(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("assess must never call the QSM dispense boundary")

        identity_assertions = IdentityAssertionRepository()
        assertion = identity_assertions.issue(
            service_user_id="wang-nainai",
            verification_method="face",
            verification_score=0.98,
        )
        medicine = MedicineRepository().get_by_id("slot-13-ibuprofen")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()
        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=identity_assertions,
            dispense_adapter=dispense,
        )
        command = AssessManualMedicationCommand(
            request_id="assess-wang-ibuprofen-001",
            medicine_id="slot-13-ibuprofen",
            slot="S13",
            service_user_id="wang-nainai",
            verification_method="face",
            verification_assertion_id=assertion.assertion_id,
            expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
        )

        first = module.assess(command)
        replay = module.assess(command)

        self.assertEqual(first.check_status, "BLOCKED")
        self.assertEqual(first.dispense_status, "NOT_STARTED")
        self.assertEqual(first.reason_codes, ["CONDITION_CONTRAINDICATION"])
        self.assertIn("既往胃溃疡", first.message)
        self.assertIn("柜门未打开", first.message)
        self.assertEqual(replay, first)
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_checks(request_id=command.request_id), 1)
        self.assertEqual(repository.count_outbox_events(check_id=first.check_id), 1)

        from app.services.medication_safety_outbox import MedicationSafetyOutbox

        event = MedicationSafetyOutbox().pending()[0]
        self.assertEqual(event.event_id, f"medication-safety:{first.check_id}")
        self.assertEqual(event.payload["check_status"], "BLOCKED")
        self.assertEqual(event.payload["dispense_status"], "NOT_STARTED")
        self.assertEqual(event.payload["profile_revision"], 1)
        self.assertEqual(event.payload["qsm_operation_id"], "")

    def test_assess_blocks_li_diabetes_for_sugared_cough_syrup(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        identity_assertions = IdentityAssertionRepository()
        assertion = identity_assertions.issue(
            service_user_id="li-yeye",
            verification_method="fingerprint",
            verification_score=92,
        )
        medicine = MedicineRepository().get_by_id("slot-05-nin-jiom-pei-pa-koa")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=identity_assertions,
        )

        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-li-ninjiom-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="fingerprint",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
            )
        )

        self.assertEqual(assessment.check_status, "BLOCKED")
        self.assertEqual(assessment.reason_codes, ["CONDITION_CONTRAINDICATION"])
        self.assertIn("2 型糖尿病", assessment.message)
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_passed_non_otc_check_requires_one_time_confirm_and_calls_dispense_once(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import (
            ManualAccessIdempotencyConflict,
            ManualMedicationAccessRepository,
        )
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
            ManualDispenseExecutionResult,
        )
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> ManualDispenseExecutionResult:
                self.calls.append(command)
                return ManualDispenseExecutionResult(
                    dispense_status="DISPENSED",
                    message="取药确认已完成，柜门已打开。",
                    dispense_record_id="dispense-manual-001",
                )

        identity_assertions = IdentityAssertionRepository()
        assertion = identity_assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
            verification_score=0.96,
        )
        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        self.assertFalse(medicine.is_otc)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()
        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=identity_assertions,
            dispense_adapter=dispense,
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-li-oseltamivir-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
            )
        )
        self.assertEqual(assessment.check_status, "PASSED")
        self.assertEqual(assessment.reason_codes, [])
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 0)

        confirm = ConfirmManualMedicationCommand(
            request_id="confirm-li-oseltamivir-001",
            safety_check_id=assessment.check_id,
            confirmed_safety_notice=True,
        )
        first = module.confirm(confirm)
        replay = module.confirm(confirm)
        with self.assertRaises(ManualAccessIdempotencyConflict):
            module.confirm(
                confirm.model_copy(update={"confirmed_safety_notice": False})
            )

        self.assertEqual(first.dispense_status, "DISPENSED")
        self.assertEqual(first.dispense_record_id, "dispense-manual-001")
        self.assertEqual(replay, first)
        self.assertEqual(len(dispense.calls), 1)
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

        from app.services.medication_safety_outbox import MedicationSafetyOutbox

        events = MedicationSafetyOutbox().pending()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_id, f"medication-safety:{assessment.check_id}")
        self.assertEqual(event.payload["check_status"], "PASSED")
        self.assertEqual(event.payload["dispense_status"], "DISPENSED")
        self.assertEqual(event.payload["persona_generation"], "senior-demo-v1")
        self.assertEqual(event.payload["profile_revision"], 1)
        self.assertEqual(
            event.payload["medicine_review_fingerprint"],
            medicine.review_fingerprint,
        )
        self.assertEqual(
            event.payload["qsm_operation_id"],
            dispense.calls[0].qsm_operation_id,
        )

    def test_concurrent_identical_confirm_requests_wait_for_and_replay_one_result(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
            ManualDispenseExecutionResult,
        )
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class BlockingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []
                self.entered = threading.Event()
                self.release = threading.Event()

            def confirm_manual(self, command: object) -> ManualDispenseExecutionResult:
                self.calls.append(command)
                self.entered.set()
                if not self.release.wait(timeout=2):
                    raise AssertionError("test did not release the fake QSM boundary")
                return ManualDispenseExecutionResult(
                    dispense_status="DISPENSED",
                    message="取药确认已完成，柜门已打开。",
                    dispense_record_id="dispense-concurrent-001",
                )

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = BlockingDispenseAdapter()
        assessment_module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
        )
        assessment = assessment_module.assess(
            AssessManualMedicationCommand(
                request_id="assess-concurrent-confirm-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )
        confirmation_barrier = threading.Barrier(2)

        class BarrierIdentityAssertions:
            def get_valid(
                self,
                assertion_id: str,
                *,
                service_user_id: str,
                verification_method: str,
            ) -> object:
                confirmation_barrier.wait(timeout=2)
                return assertions.get_valid(
                    assertion_id,
                    service_user_id=service_user_id,
                    verification_method=verification_method,
                )

        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=BarrierIdentityAssertions(),
            dispense_adapter=dispense,
        )
        confirm = ConfirmManualMedicationCommand(
            request_id="confirm-concurrent-001",
            safety_check_id=assessment.check_id,
            confirmed_safety_notice=True,
        )
        results: list[object] = []
        errors: list[BaseException] = []

        def run_confirm() -> None:
            try:
                results.append(module.confirm(confirm))
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = threading.Thread(target=run_confirm)
        second = threading.Thread(target=run_confirm)
        first.start()
        second.start()
        self.assertTrue(dispense.entered.wait(timeout=2))
        first.join(timeout=0.1)
        second.join(timeout=0.1)
        self.assertTrue(first.is_alive(), "the active confirmation must still own the QSM call")
        self.assertTrue(second.is_alive(), "the concurrent replay must wait for the active result")
        dispense.release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(dispense.calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual({result.dispense_status for result in results}, {"DISPENSED"})
        self.assertEqual(
            {result.dispense_record_id for result in results},
            {"dispense-concurrent-001"},
        )
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_abandoned_confirm_is_atomically_terminalized_for_concurrent_replays(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule
        from app.services.medication_safety_outbox import MedicationSafetyOutbox

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        assessment = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-abandoned-confirm-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )
        payload_digest = "abandoned-confirm-payload-digest"
        claimed = repository.begin_confirm(
            request_id="confirm-abandoned-001",
            request_payload_digest=payload_digest,
            check_id=assessment.check_id,
            qsm_operation_id="manual-abandoned-operation-001",
            consumed_at=db.now_text(),
        )
        self.assertTrue(claimed)

        barrier = threading.Barrier(2)
        outcomes: list[object] = []
        errors: list[BaseException] = []

        def replay_after_owner_exit() -> None:
            try:
                barrier.wait(timeout=2)
                outcomes.append(
                    repository.get_confirm_replay(
                        request_id="confirm-abandoned-001",
                        request_payload_digest=payload_digest,
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with (
            patch.object(repository, "_CONFIRM_REPLAY_WAIT_SECONDS", 0.05),
            patch.object(repository, "_CONFIRM_REPLAY_POLL_SECONDS", 0.005),
        ):
            first = threading.Thread(target=replay_after_owner_exit)
            second = threading.Thread(target=replay_after_owner_exit)
            first.start()
            second.start()
            first.join(timeout=2)
            second.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(
            {outcome.dispense_status for outcome in outcomes},
            {"RESULT_UNKNOWN"},
        )
        self.assertEqual(
            repository.count_outbox_events(check_id=assessment.check_id),
            1,
        )
        terminal_replay = repository.get_confirm_replay(
            request_id="confirm-abandoned-001",
            request_payload_digest=payload_digest,
        )
        self.assertEqual(terminal_replay.dispense_status, "RESULT_UNKNOWN")
        late_owner = repository.complete_confirm(
            check_id=assessment.check_id,
            dispense_status="DISPENSED",
            message="late owner must not overwrite the recovered terminal result",
            dispense_record_id="dispense-too-late-001",
            completed_at=db.now_text(),
        )
        self.assertEqual(late_owner.dispense_status, "RESULT_UNKNOWN")
        self.assertEqual(
            repository.count_outbox_events(check_id=assessment.check_id),
            1,
        )
        event = MedicationSafetyOutbox().pending()[0]
        self.assertEqual(event.payload["check_status"], "PASSED")
        self.assertEqual(event.payload["dispense_status"], "RESULT_UNKNOWN")
        self.assertEqual(
            event.payload["qsm_operation_id"],
            "manual-abandoned-operation-001",
        )

    def test_registered_face_match_returns_a_short_lived_identity_assertion(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.services.identity_service import IdentityService

        class MatchedFaceClient:
            @staticmethod
            def identify() -> dict[str, object]:
                return {
                    "status": "matched",
                    "subject": "profile:wang-nainai",
                    "confidence": 0.97,
                }

        IdentityService._bind("profile:wang-nainai", "wang-nainai", 0.97)

        response = IdentityService(face_client=MatchedFaceClient()).resolve()

        self.assertTrue(response.ok)
        self.assertEqual(response.user.id, "wang-nainai")
        self.assertTrue(response.verification_assertion_id.startswith("identity-assertion-"))
        assertion = IdentityAssertionRepository().get_valid(
            response.verification_assertion_id,
            service_user_id="wang-nainai",
            verification_method="face",
        )
        self.assertIsNotNone(assertion)

    def test_registered_fingerprint_match_returns_a_short_lived_identity_assertion(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.services.fingerprint_service import FingerprintService

        class MatchedFingerprintClient:
            @staticmethod
            def identify(*, timeout: int) -> dict[str, object]:
                del timeout
                return {"ok": True, "matched": True, "id": 21, "score": 91}

        FingerprintService._bind_identity("li-yeye", 21)

        response = FingerprintService(client=MatchedFingerprintClient()).identify()

        self.assertTrue(response.ok)
        self.assertEqual(response.user.id, "li-yeye")
        self.assertTrue(response.verification_assertion_id.startswith("identity-assertion-"))
        assertion = IdentityAssertionRepository().get_valid(
            response.verification_assertion_id,
            service_user_id="li-yeye",
            verification_method="fingerprint",
        )
        self.assertIsNotNone(assertion)

    def test_direct_manual_dispense_is_rejected_but_validated_adapter_calls_qsm_once(self) -> None:
        from app.schemas.dispense import DispenseConfirmRequest
        from app.schemas.manual_medication_access import ManualDispenseExecutionCommand
        from app.services.dispense_service import DispenseError, DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, bool, str]] = []

            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                self.calls.append((slot, quantity, dry_run, operation_id))
                return {"ok": True, "detail": "fake cabinet opened"}

        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        qsm = RecordingQsm()
        service = DispenseService(qsm_client=qsm)
        direct = DispenseConfirmRequest(
            medicine_id=medicine.id,
            slot=medicine.slot,
            quantity=1,
            reason="direct manual bypass attempt",
            confirmed_safety_notice=True,
            confirm_real_dispense=True,
            target_user_id="li-yeye",
            target_user_name="李爷爷",
            verification_method="face",
        )

        with self.assertRaisesRegex(DispenseError, "安全核查"):
            service.confirm(direct)
        self.assertEqual(qsm.calls, [])

        execution = self._manual_execution_command(
            medicine_id=medicine.id,
            operation_id="manual-op-001",
            expected_stock=medicine.stock,
        )
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )
        with patch("app.services.dispense_service.settings", fake_settings):
            outcome = DispenseServiceManualAdapter(service).confirm_manual(execution)

        self.assertEqual(outcome.dispense_status, "DISPENSED")
        self.assertEqual(qsm.calls, [("14", 1, False, "manual-op-001")])

    def test_distinct_manual_operations_keep_the_availability_flag_at_one(self) -> None:
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import ManualDispenseExecutionCommand
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, bool, str]] = []

            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                self.calls.append((slot, quantity, dry_run, operation_id))
                return {"ok": True, "detail": "fake cabinet opened"}

        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET stock=1 WHERE id='slot-14-oseltamivir'"
            )
        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        person = ManualMedicationAccessRepository().get_person("li-yeye")
        self.assertIsNotNone(medicine)
        self.assertIsNotNone(person)
        command = self._manual_execution_command(
            medicine_id=medicine.id,
            operation_id="manual-last-stock-001",
            expected_stock=1,
        )
        qsm = RecordingQsm()
        adapter = DispenseServiceManualAdapter(DispenseService(qsm_client=qsm))
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            first = adapter.confirm_manual(command)
            second = adapter.confirm_manual(
                command.model_copy(
                    update={"qsm_operation_id": "manual-last-stock-002"}
                )
            )

        self.assertEqual(first.dispense_status, "DISPENSED")
        self.assertEqual(second.dispense_status, "DISPENSED")
        self.assertEqual(
            qsm.calls,
            [
                ("14", 1, False, "manual-last-stock-001"),
                ("14", 1, False, "manual-last-stock-002"),
            ],
        )
        self.assertEqual(
            MedicineRepository().get_by_id(medicine.id).stock,
            1,
        )

    def test_known_manual_hardware_failure_keeps_the_availability_flag(self) -> None:
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter

        class FailedQsm:
            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                del slot, quantity, dry_run, operation_id
                return {
                    "ok": False,
                    "result_unknown": False,
                    "detail": "cabinet motor rejected the command",
                }

        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET stock=1 WHERE id='slot-14-oseltamivir'"
            )
        command = self._manual_execution_command(
            medicine_id="slot-14-oseltamivir",
            operation_id="manual-known-failure-stock-001",
            expected_stock=1,
        )
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            outcome = DispenseServiceManualAdapter(
                DispenseService(qsm_client=FailedQsm())
            ).confirm_manual(command)

        self.assertEqual(outcome.dispense_status, "HARDWARE_FAILED")
        self.assertFalse(outcome.inventory_confirmation_required)
        refreshed = MedicineRepository().get_by_id(command.medicine_id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.stock, 1)
        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, "")

    def test_hardware_failure_does_not_overwrite_a_concurrent_stock_change(self) -> None:
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter

        class FailedQsmAfterExternalStockChange:
            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                del slot, quantity, dry_run, operation_id
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE medicines SET stock=5 WHERE id='slot-14-oseltamivir'"
                    )
                return {
                    "ok": False,
                    "result_unknown": False,
                    "detail": "cabinet motor rejected the command",
                }

        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET stock=1 WHERE id='slot-14-oseltamivir'"
            )
        command = self._manual_execution_command(
            medicine_id="slot-14-oseltamivir",
            operation_id="manual-failure-stock-cas-001",
            expected_stock=1,
        )
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            outcome = DispenseServiceManualAdapter(
                DispenseService(qsm_client=FailedQsmAfterExternalStockChange())
            ).confirm_manual(command)

        self.assertEqual(outcome.dispense_status, "HARDWARE_FAILED")
        self.assertIn("外设开柜失败", outcome.message)
        self.assertEqual(
            MedicineRepository().get_by_id(command.medicine_id).stock,
            5,
        )

    def test_unknown_manual_hardware_result_keeps_stable_available_stock(self) -> None:
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter

        class UnknownQsm:
            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                del slot, quantity, dry_run, operation_id
                return {
                    "ok": False,
                    "result_unknown": True,
                    "retry_safe": False,
                    "detail": "result was lost after the command was sent",
                }

        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET stock=1 WHERE id='slot-14-oseltamivir'"
            )
        command = self._manual_execution_command(
            medicine_id="slot-14-oseltamivir",
            operation_id="manual-unknown-stock-001",
            expected_stock=1,
        )
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            outcome = DispenseServiceManualAdapter(
                DispenseService(qsm_client=UnknownQsm())
            ).confirm_manual(command)

        self.assertEqual(outcome.dispense_status, "RESULT_UNKNOWN")
        self.assertFalse(outcome.inventory_confirmation_required)
        refreshed = MedicineRepository().get_by_id(command.medicine_id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.stock, 1)
        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, "")

    def test_manual_dry_run_does_not_reserve_stock(self) -> None:
        from app.services.dispense_service import DispenseService

        class DryRunQsm:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, bool, str]] = []

            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                self.calls.append((slot, quantity, dry_run, operation_id))
                return {"ok": True, "detail": "dry run only"}

        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET stock=1 WHERE id='slot-14-oseltamivir'"
            )
        command = self._manual_execution_command(
            medicine_id="slot-14-oseltamivir",
            operation_id="manual-dry-run-stock-001",
            expected_stock=1,
        )
        qsm = DryRunQsm()
        fake_settings = SimpleNamespace(
            dispense_dry_run=True,
            enable_real_dispense=False,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            response = DispenseService(qsm_client=qsm).confirm_checked_manual(command)

        self.assertTrue(response.ok)
        self.assertTrue(response.dry_run)
        self.assertFalse(response.inventory_confirmation_required)
        self.assertEqual(
            qsm.calls,
            [("14", 1, True, "manual-dry-run-stock-001")],
        )
        refreshed = MedicineRepository().get_by_id(command.medicine_id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.stock, 1)
        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, "")

    def test_manual_execution_command_rejects_non_positive_quantity(self) -> None:
        from app.schemas.manual_medication_access import ManualDispenseExecutionCommand

        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        valid = self._manual_execution_command(
            medicine_id=medicine.id,
            operation_id="manual-invalid-quantity-001",
            expected_stock=medicine.stock,
        )

        with self.assertRaises(ValueError):
            ManualDispenseExecutionCommand.model_validate(
                {**valid.model_dump(), "quantity": 0}
            )

    def test_manual_adapter_distinguishes_an_ambiguous_transport_result_from_hardware_failure(self) -> None:
        from app.schemas.manual_medication_access import ManualDispenseExecutionCommand
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter

        class AmbiguousQsm:
            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                del slot, quantity, dry_run, operation_id
                return {
                    "ok": False,
                    "result_unknown": True,
                    "detail": "request timed out after write",
                }

        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        service = DispenseService(qsm_client=AmbiguousQsm())
        execution = self._manual_execution_command(
            medicine_id=medicine.id,
            operation_id="manual-op-ambiguous-001",
            expected_stock=medicine.stock,
        )
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            outcome = DispenseServiceManualAdapter(service).confirm_manual(execution)

        self.assertEqual(outcome.dispense_status, "RESULT_UNKNOWN")
        self.assertIn("待现场确认", outcome.message)

    def test_qsm_transport_error_is_reported_as_an_ambiguous_physical_result(self) -> None:
        from app.services.qsm_client import QsmClient

        client = QsmClient(mode="real")
        with patch.object(
            client,
            "_request_json",
            return_value=({}, "timed out after request write"),
        ):
            result = client.dispense("14", 1, dry_run=False)

        self.assertFalse(result["ok"])
        self.assertTrue(result["result_unknown"])

    def test_qsm_gateway_result_unknown_is_promoted_from_a_successful_http_response(self) -> None:
        from app.services.qsm_client import QsmClient

        client = QsmClient(mode="real")
        with patch.object(
            client,
            "_request_json",
            return_value=(
                {
                    "ok": False,
                    "result_unknown": True,
                    "retry_safe": False,
                    "detail": "operation was sent but its result was not persisted",
                },
                None,
            ),
        ):
            result = client.dispense(
                "14",
                1,
                dry_run=False,
                operation_id="manual-operation-unknown-001",
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["result_unknown"])
        self.assertFalse(result["retry_safe"])

    def test_manual_access_assess_router_returns_structured_business_block(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.routers.manual_medication_access import assess_manual_medication
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="wang-nainai",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-13-ibuprofen")
        repository = ManualMedicationAccessRepository()
        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
        )
        response = assess_manual_medication(
            AssessManualMedicationCommand(
                request_id="router-assess-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="wang-nainai",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
            ),
            module=module,
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.check_status, "BLOCKED")
        self.assertEqual(response.reason_codes, ["CONDITION_CONTRAINDICATION"])

    def test_public_medicine_model_exposes_the_server_review_fingerprint(self) -> None:
        medicine = MedicineRepository().get_by_id("slot-13-ibuprofen")

        self.assertTrue(medicine.review_fingerprint)
        self.assertEqual(
            medicine.review_fingerprint,
            MedicineRepository.review_fingerprint(medicine),
        )

    def test_qsm_boundary_exception_becomes_result_unknown_and_is_never_retried(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
        )
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class AmbiguousDispenseAdapter:
            def __init__(self) -> None:
                self.calls = 0

            def confirm_manual(self, command: object) -> object:
                del command
                self.calls += 1
                raise TimeoutError("response lost after write")

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="fingerprint",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        repository = ManualMedicationAccessRepository()
        adapter = AmbiguousDispenseAdapter()
        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
            dispense_adapter=adapter,
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-result-unknown-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="fingerprint",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )
        self.assertEqual(assessment.check_status, "PASSED")
        command = ConfirmManualMedicationCommand(
            request_id="confirm-result-unknown-001",
            safety_check_id=assessment.check_id,
            confirmed_safety_notice=True,
        )

        first = module.confirm(command)
        replay = module.confirm(command)

        self.assertEqual(first.dispense_status, "RESULT_UNKNOWN")
        self.assertFalse(first.ok)
        self.assertIn("请勿自动重试", first.message)
        self.assertEqual(replay, first)
        self.assertEqual(adapter.calls, 1)

    def test_known_pre_qsm_dispense_rejection_invalidates_the_pass(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
        )
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def dispense(self, *args: object, **kwargs: object) -> dict[str, object]:
                self.calls.append((args, kwargs))
                return {"ok": True, "detail": "fake cabinet opened"}

        class RacingStockAdapter:
            def __init__(self, delegate: DispenseServiceManualAdapter) -> None:
                self.delegate = delegate
                self.calls = 0

            def confirm_manual(self, command: object) -> object:
                self.calls += 1
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE medicines SET stock=stock+1 WHERE id=?",
                        (command.medicine_id,),
                    )
                return self.delegate.confirm_manual(command)

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        qsm = RecordingQsm()
        adapter = RacingStockAdapter(
            DispenseServiceManualAdapter(DispenseService(qsm_client=qsm))
        )
        module = ManualMedicationAccessModule(
            identity_assertions=assertions,
            dispense_adapter=adapter,
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-known-pre-qsm-rejection-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        command = ConfirmManualMedicationCommand(
            request_id="confirm-known-pre-qsm-rejection-001",
            safety_check_id=assessment.check_id,
            confirmed_safety_notice=True,
        )
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )
        with patch("app.services.dispense_service.settings", fake_settings):
            with self.assertRaisesRegex(ValueError, "库存记录已经变化"):
                module.confirm(command)
            with self.assertRaisesRegex(ValueError, "库存记录已经变化"):
                module.confirm(command)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(qsm.calls, [])
        stored = ManualMedicationAccessRepository().get_check(assessment.check_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.check_status, "CHECK_FAILED")
        self.assertEqual(stored.dispense_status, "NOT_STARTED")
        self.assertEqual(
            ManualMedicationAccessRepository().count_outbox_events(
                check_id=assessment.check_id
            ),
            1,
        )

    def test_person_safety_facts_are_rechecked_at_the_final_qsm_seam(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
        )
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, bool, str]] = []

            def dispense(
                self,
                slot: str,
                quantity: int,
                *,
                dry_run: bool,
                operation_id: str = "",
            ) -> dict[str, object]:
                self.calls.append((slot, quantity, dry_run, operation_id))
                return {"ok": True, "detail": "fake cabinet opened"}

        class MutatingAdapter:
            def __init__(self, delegate: DispenseServiceManualAdapter) -> None:
                self.delegate = delegate

            def confirm_manual(self, command: object) -> object:
                with db.connect() as conn:
                    conn.execute(
                        """
                        UPDATE service_users
                        SET current_medications_json=?
                        WHERE id='li-yeye'
                        """,
                        (
                            json.dumps(
                                [
                                    {
                                        "medicine_name": "核查后新增的长期用药",
                                        "active_ingredients": ["新增长期用药成分"],
                                    }
                                ],
                                ensure_ascii=False,
                            ),
                        ),
                    )
                return self.delegate.confirm_manual(command)

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        qsm = RecordingQsm()
        module = ManualMedicationAccessModule(
            identity_assertions=assertions,
            dispense_adapter=MutatingAdapter(
                DispenseServiceManualAdapter(DispenseService(qsm_client=qsm))
            ),
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-final-person-snapshot-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )
        self.assertEqual(assessment.check_status, "PASSED")

        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )
        with patch("app.services.dispense_service.settings", fake_settings):
            with self.assertRaisesRegex(ValueError, "人物资料已经更新"):
                module.confirm(
                    ConfirmManualMedicationCommand(
                        request_id="confirm-final-person-snapshot-001",
                        safety_check_id=assessment.check_id,
                        confirmed_safety_notice=True,
                    )
                )

        self.assertEqual(qsm.calls, [])
        stored = ManualMedicationAccessRepository().get_check(assessment.check_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.check_status, "CHECK_FAILED")
        self.assertEqual(stored.dispense_status, "NOT_STARTED")
        self.assertEqual(
            ManualMedicationAccessRepository().count_outbox_events(
                check_id=assessment.check_id
            ),
            1,
        )

        from app.services.medication_safety_outbox import MedicationSafetyOutbox

        event = MedicationSafetyOutbox().pending()[0]
        self.assertEqual(event.payload["check_status"], "CHECK_FAILED")
        self.assertEqual(event.payload["dispense_status"], "NOT_STARTED")
        self.assertEqual(event.payload["reason_codes"], ["PROFILE_GENERATION_MISMATCH"])
        self.assertEqual(event.payload["qsm_operation_id"], "")

    def test_new_contraindication_at_the_final_seam_records_blocked_without_qsm(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
        )
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter
        from app.services.manual_medication_access_module import ManualMedicationAccessModule
        from app.services.medication_safety_outbox import MedicationSafetyOutbox

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def dispense(self, *args: object, **kwargs: object) -> dict[str, object]:
                self.calls.append((args, kwargs))
                return {"ok": True, "detail": "fake cabinet opened"}

        class AddingContraindicationAdapter:
            def __init__(self, delegate: DispenseServiceManualAdapter) -> None:
                self.delegate = delegate

            def confirm_manual(self, command: object) -> object:
                with db.connect() as conn:
                    conn.execute(
                        """
                        UPDATE service_users SET medical_conditions_json=?
                        WHERE id='li-yeye'
                        """,
                        (
                            json.dumps(
                                [
                                    {
                                        "concept_code": "peptic_ulcer",
                                        "display_text": "活动性消化性溃疡",
                                        "status": "present",
                                    }
                                ],
                                ensure_ascii=False,
                            ),
                        ),
                    )
                return self.delegate.confirm_manual(command)

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-13-ibuprofen")
        self.assertIsNotNone(medicine)
        qsm = RecordingQsm()
        module = ManualMedicationAccessModule(
            identity_assertions=assertions,
            dispense_adapter=AddingContraindicationAdapter(
                DispenseServiceManualAdapter(DispenseService(qsm_client=qsm))
            ),
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-final-new-contraindication-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )
        self.assertEqual(assessment.check_status, "PASSED")
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            with self.assertRaisesRegex(ValueError, "活动性消化性溃疡"):
                module.confirm(
                    ConfirmManualMedicationCommand(
                        request_id="confirm-final-new-contraindication-001",
                        safety_check_id=assessment.check_id,
                        confirmed_safety_notice=True,
                    )
                )

        self.assertEqual(qsm.calls, [])
        stored = ManualMedicationAccessRepository().get_check(assessment.check_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.check_status, "BLOCKED")
        event = MedicationSafetyOutbox().pending()[0]
        self.assertEqual(event.payload["check_status"], "BLOCKED")
        self.assertEqual(event.payload["dispense_status"], "NOT_STARTED")
        self.assertEqual(event.payload["reason_codes"], ["CONDITION_CONTRAINDICATION"])
        self.assertEqual(event.payload["qsm_operation_id"], "")

    def test_identity_assertion_is_rechecked_at_the_final_qsm_seam(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
        )
        from app.services.dispense_service import DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def dispense(self, *args: object, **kwargs: object) -> dict[str, object]:
                self.calls.append((args, kwargs))
                return {"ok": True, "detail": "fake cabinet opened"}

        class ExpiringAssertionAdapter:
            def __init__(self, delegate: DispenseServiceManualAdapter) -> None:
                self.delegate = delegate

            def confirm_manual(self, command: object) -> object:
                with db.connect() as conn:
                    conn.execute(
                        """
                        UPDATE identity_assertions SET expires_at='2000-01-01 00:00:00'
                        WHERE assertion_id=?
                        """,
                        (command.verification_assertion_id,),
                    )
                return self.delegate.confirm_manual(command)

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="fingerprint",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        qsm = RecordingQsm()
        module = ManualMedicationAccessModule(
            identity_assertions=assertions,
            dispense_adapter=ExpiringAssertionAdapter(
                DispenseServiceManualAdapter(DispenseService(qsm_client=qsm))
            ),
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-final-assertion-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="fingerprint",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )
        self.assertEqual(assessment.check_status, "PASSED")
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            with self.assertRaisesRegex(ValueError, "未找到可用于核查"):
                module.confirm(
                    ConfirmManualMedicationCommand(
                        request_id="confirm-final-assertion-001",
                        safety_check_id=assessment.check_id,
                        confirmed_safety_notice=True,
                    )
                )

        self.assertEqual(qsm.calls, [])
        stored = ManualMedicationAccessRepository().get_check(assessment.check_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.check_status, "CHECK_FAILED")
        self.assertEqual(stored.dispense_status, "NOT_STARTED")

    def test_atomic_qsm_seam_catches_person_change_after_service_precheck(self) -> None:
        from app.services.dispense_service import DispenseError, DispenseService
        from app.services.manual_dispense_adapter import DispenseServiceManualAdapter

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def dispense(self, *args: object, **kwargs: object) -> dict[str, object]:
                self.calls.append((args, kwargs))
                return {"ok": True, "detail": "fake cabinet opened"}

        class RacingDispenseService(DispenseService):
            def _validate_manual_execution_snapshot(self, command, medicine) -> None:
                super()._validate_manual_execution_snapshot(command, medicine)
                with db.connect() as conn:
                    conn.execute(
                        """
                        UPDATE service_users SET allergies='核查后新增过敏事实'
                        WHERE id='li-yeye'
                        """
                    )

        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        command = self._manual_execution_command(
            medicine_id=medicine.id,
            operation_id="manual-atomic-person-race-001",
            expected_stock=medicine.stock,
        )
        qsm = RecordingQsm()
        fake_settings = SimpleNamespace(
            dispense_dry_run=False,
            enable_real_dispense=True,
            real_dispense_test_slot="",
        )

        with patch("app.services.dispense_service.settings", fake_settings):
            with self.assertRaisesRegex(DispenseError, "人物资料已经更新"):
                DispenseServiceManualAdapter(
                    RacingDispenseService(qsm_client=qsm)
                ).confirm_manual(command)

        self.assertEqual(qsm.calls, [])
        self.assertEqual(
            MedicineRepository().get_by_id(command.medicine_id).stock,
            command.expected_stock,
        )

    def test_guest_profile_fails_closed_before_the_dispense_boundary(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(id, name, age, profile, allergies, note, status)
                VALUES ('guest-manual-test', '游客测试', 0, '未登记', '', '测试', '游客')
                """
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="guest-manual-test",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        repository = ManualMedicationAccessRepository()
        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
        )

        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-guest-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="guest-manual-test",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

        from app.services.medication_safety_outbox import MedicationSafetyOutbox

        event = MedicationSafetyOutbox().pending()[0]
        self.assertEqual(event.event_id, f"medication-safety:{assessment.check_id}")
        self.assertEqual(event.payload["check_status"], "CHECK_FAILED")
        self.assertEqual(event.payload["dispense_status"], "NOT_STARTED")
        self.assertEqual(event.payload["medicine_review_fingerprint"], medicine.review_fingerprint)
        self.assertEqual(event.payload["qsm_operation_id"], "")

    def test_same_assess_request_id_with_different_payload_is_rejected(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import (
            ManualAccessIdempotencyConflict,
            ManualMedicationAccessRepository,
        )
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="wang-nainai",
            verification_method="face",
        )
        ibuprofen = MedicineRepository().get_by_id("slot-13-ibuprofen")
        iodophor = MedicineRepository().get_by_id("slot-17-iodophor")
        repository = ManualMedicationAccessRepository()
        module = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
        )
        first = AssessManualMedicationCommand(
            request_id="assess-idempotency-001",
            medicine_id=ibuprofen.id,
            slot=ibuprofen.slot,
            service_user_id="wang-nainai",
            verification_method="face",
            verification_assertion_id=assertion.assertion_id,
            expected_review_fingerprint=ibuprofen.review_fingerprint,
        )
        changed = first.model_copy(
            update={
                "medicine_id": iodophor.id,
                "slot": iodophor.slot,
                "expected_review_fingerprint": iodophor.review_fingerprint,
            }
        )

        module.assess(first)
        with self.assertRaises(ManualAccessIdempotencyConflict):
            module.assess(changed)

        self.assertEqual(repository.count_checks(request_id=first.request_id), 1)
        self.assertEqual(repository.count_outbox_events(), 1)

    def test_reviewed_ingredient_interaction_blocks_manual_access(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        medicine_repository = MedicineRepository()
        medicine_repository.save_ingredient_conflict(
            left_ingredient="乳果糖",
            right_ingredient="聚维酮碘",
            disposition="block",
            message="测试用已审核相互作用",
            review_status="reviewed",
            reviewed_by="test-pharmacist",
            reviewed_at="2026-08-10 08:00:00",
        )
        medicine = medicine_repository.get_by_id("slot-17-iodophor")
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        module = ManualMedicationAccessModule(
            repository=ManualMedicationAccessRepository(),
            identity_assertions=assertions,
            medicine_repository=medicine_repository,
        )

        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-reviewed-interaction-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "BLOCKED")
        self.assertEqual(assessment.reason_codes, ["REVIEWED_INTERACTION"])
        self.assertIn("测试用已审核相互作用", assessment.message)

    def test_assess_preserves_all_conflicts_at_the_same_block_priority(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        with db.connect() as conn:
            conn.execute(
                """
                UPDATE service_users
                SET medical_conditions_json=?, current_medications_json=?
                WHERE id='li-yeye'
                """,
                (
                    json.dumps(
                        [
                            {
                                "concept_code": "peptic_ulcer",
                                "display_text": "活动性消化性溃疡",
                                "status": "present",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            {
                                "medicine_name": "另一种布洛芬制剂",
                                "active_ingredients": ["布洛芬"],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-13-ibuprofen")
        self.assertIsNotNone(medicine)

        assessment = ManualMedicationAccessModule(
            identity_assertions=assertions,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-multiple-block-reasons-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "BLOCKED")
        self.assertEqual(
            assessment.reason_codes,
            ["CONDITION_CONTRAINDICATION", "DUPLICATE_ACTIVE_INGREDIENT"],
        )
        self.assertIn("活动性消化性溃疡", assessment.message)
        self.assertIn("重复成分“布洛芬”", assessment.message)

    def test_structured_allergy_blocks_manual_access(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        medicine = MedicineRepository().get_by_id("slot-04-amoxicillin")
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="wang-nainai",
            verification_method="fingerprint",
        )
        module = ManualMedicationAccessModule(
            repository=ManualMedicationAccessRepository(),
            identity_assertions=assertions,
        )

        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-wang-amoxicillin-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="wang-nainai",
                verification_method="fingerprint",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "BLOCKED")
        self.assertEqual(assessment.reason_codes, ["ALLERGY_CONFLICT"])
        self.assertIn("青霉素", assessment.message)

    def test_legacy_allergies_block_manual_access_without_structured_allergy_facts(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  persona_generation, safety_profile_revision
                ) VALUES (
                  'legacy-allergy-person', '旧档案人物', 68, '旧版健康档案',
                  '青霉素类药物过敏', '', '已登记', 'legacy-profile-v1', 1
                )
                """
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="legacy-allergy-person",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-04-amoxicillin")
        self.assertIsNotNone(medicine)

        assessment = ManualMedicationAccessModule(
            identity_assertions=assertions,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-legacy-allergy-amoxicillin-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="legacy-allergy-person",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "BLOCKED")
        self.assertEqual(assessment.reason_codes, ["ALLERGY_CONFLICT"])
        self.assertIn("青霉素类药物过敏", assessment.message)

    def test_missing_medical_history_axis_cannot_pass_manual_access(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("incomplete profiles must never reach QSM")

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  current_medications_json, persona_generation, safety_profile_revision
                ) VALUES (
                  'missing-medical-history', '缺病史结论档案', 68, '旧版健康档案',
                  '无已知药物过敏', '', '已登记', ?, 'legacy-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "medicine_name": "维生素 C 片",
                                "active_ingredients": ["维生素C"],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="missing-medical-history",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()

        assessment = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
            dispense_adapter=dispense,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-missing-medical-history-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="missing-medical-history",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertEqual(assessment.expires_at, "")
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_missing_current_medication_axis_cannot_pass_manual_access(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("incomplete profiles must never reach QSM")

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, persona_generation, safety_profile_revision
                ) VALUES (
                  'missing-current-medication', '缺当前用药结论档案', 68, '旧版健康档案',
                  '无已知药物过敏', '', '已登记', ?, 'legacy-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "concept_code": "hypertension",
                                "display_text": "高血压",
                                "status": "present",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="missing-current-medication",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()

        assessment = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
            dispense_adapter=dispense,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-missing-current-medication-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="missing-current-medication",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertEqual(assessment.expires_at, "")
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_missing_allergy_axis_cannot_pass_manual_access(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("incomplete profiles must never reach QSM")

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  persona_generation, safety_profile_revision
                ) VALUES (
                  'missing-allergy', '缺过敏结论档案', 68, '结构化健康档案',
                  '', '', '已登记', ?, ?, 'structured-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "concept_code": "hypertension",
                                "display_text": "高血压",
                                "status": "present",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            {
                                "medicine_name": "维生素 C 片",
                                "active_ingredients": ["维生素C"],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="missing-allergy",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()

        assessment = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
            dispense_adapter=dispense,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-missing-allergy-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="missing-allergy",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertEqual(assessment.expires_at, "")
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_unstructured_medical_history_cannot_pass_manual_access(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("unreviewable profiles must never reach QSM")

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  persona_generation, safety_profile_revision
                ) VALUES (
                  'unstructured-medical-history', '病史不可核查档案', 68,
                  '结构化健康档案', '无已知药物过敏', '', '已登记',
                  ?, ?, 'structured-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [{"display_text": "高血压", "status": "present"}],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            {
                                "medicine_name": "维生素 C 片",
                                "active_ingredients": ["维生素C"],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="unstructured-medical-history",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()

        assessment = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
            dispense_adapter=dispense,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-unstructured-medical-history-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="unstructured-medical-history",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertEqual(assessment.expires_at, "")
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_current_medication_without_active_ingredients_cannot_pass(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("unreviewable profiles must never reach QSM")

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  persona_generation, safety_profile_revision
                ) VALUES (
                  'medication-without-ingredients', '当前用药不可核查档案', 68,
                  '结构化健康档案', '无已知药物过敏', '', '已登记',
                  ?, ?, 'structured-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "concept_code": "hypertension",
                                "display_text": "高血压",
                                "status": "present",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [{"medicine_name": "成分待补录的长期用药"}],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="medication-without-ingredients",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()

        assessment = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
            dispense_adapter=dispense,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-medication-without-ingredients-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="medication-without-ingredients",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertEqual(assessment.expires_at, "")
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_allergy_fact_without_matchable_substance_cannot_pass(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("unreviewable profiles must never reach QSM")

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  allergy_facts_json, persona_generation, safety_profile_revision
                ) VALUES (
                  'allergy-without-substance', '过敏事实不可核查档案', 68,
                  '结构化健康档案', '', '', '已登记',
                  ?, ?, ?, 'structured-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "concept_code": "hypertension",
                                "display_text": "高血压",
                                "status": "present",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            {
                                "medicine_name": "维生素 C 片",
                                "active_ingredients": ["维生素C"],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps([{"status": "present"}], ensure_ascii=False),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="allergy-without-substance",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)
        repository = ManualMedicationAccessRepository()
        dispense = RecordingDispenseAdapter()

        assessment = ManualMedicationAccessModule(
            repository=repository,
            identity_assertions=assertions,
            dispense_adapter=dispense,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-allergy-without-substance-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="allergy-without-substance",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertEqual(assessment.expires_at, "")
        self.assertIn("柜门未打开", assessment.message)
        self.assertEqual(dispense.calls, [])
        self.assertEqual(repository.count_outbox_events(check_id=assessment.check_id), 1)

    def test_unknown_legacy_allergy_text_is_not_an_auditable_conclusion(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  persona_generation, safety_profile_revision
                ) VALUES (
                  'unknown-legacy-allergy', '过敏结论待补人物', 68,
                  '结构化健康档案', '未知', '', '已登记',
                  ?, ?, 'structured-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "concept_code": "hypertension",
                                "display_text": "高血压",
                                "status": "absent",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            {
                                "medicine_name": "维生素 C 片",
                                "active_ingredients": ["维生素C"],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="unknown-legacy-allergy",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)

        assessment = ManualMedicationAccessModule(
            identity_assertions=assertions,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-unknown-legacy-allergy-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="unknown-legacy-allergy",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["PROFILE_UNAVAILABLE"])
        self.assertIn("柜门未打开", assessment.message)

    def test_explicit_no_current_medication_conclusion_is_auditable(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  allergy_facts_json, persona_generation, safety_profile_revision
                ) VALUES (
                  'explicit-no-current-medicine', '明确未用药人物', 68,
                  '结构化健康档案', '', '', '已登记',
                  ?, ?, ?, 'structured-profile-v1', 1
                )
                """,
                (
                    json.dumps(
                        [
                            {
                                "concept_code": "hypertension",
                                "display_text": "高血压",
                                "status": "absent",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            {
                                "status": "absent",
                                "display_text": "当前未使用任何药物",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            {
                                "status": "absent",
                                "display_text": "无已知药物过敏",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="explicit-no-current-medicine",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        self.assertIsNotNone(medicine)

        assessment = ManualMedicationAccessModule(
            identity_assertions=assertions,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-explicit-no-current-medicine-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="explicit-no-current-medicine",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )

        self.assertEqual(assessment.check_status, "PASSED")

    def test_unknown_current_medication_status_is_not_auditable(self) -> None:
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        self.assertFalse(
            ManualMedicationAccessModule._has_auditable_current_medications(
                (
                    {
                        "status": "unknown",
                        "medicine_name": "待核对药物",
                        "active_ingredients": ["维生素C"],
                    },
                )
            )
        )

    def test_english_legacy_allergy_placeholders_are_not_auditable(self) -> None:
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        for placeholder in ("unknown", "pending confirmation", "unconfirmed"):
            with self.subTest(placeholder=placeholder):
                self.assertFalse(
                    ManualMedicationAccessModule._has_auditable_allergy_conclusion(
                        (), placeholder
                    )
                )
    def test_profile_revision_change_invalidates_a_pass_before_qsm(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
        )
        from app.schemas.records import ServiceUserUpdateRequest
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> object:
                self.calls.append(command)
                raise AssertionError("profile change must be rejected before QSM")

        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        adapter = RecordingDispenseAdapter()
        module = ManualMedicationAccessModule(
            repository=ManualMedicationAccessRepository(),
            identity_assertions=assertions,
            dispense_adapter=adapter,
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-profile-revision-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=medicine.review_fingerprint,
            )
        )
        RecordsService().update_service_user(
            "li-yeye",
            ServiceUserUpdateRequest(
                medical_conditions=[
                    {
                        "concept_code": "diabetes",
                        "display_text": "2 型糖尿病（资料已复核）",
                        "status": "present",
                    }
                ]
            ),
        )

        with self.assertRaisesRegex(ValueError, "人物资料已经更新"):
            module.confirm(
                ConfirmManualMedicationCommand(
                    request_id="confirm-profile-revision-001",
                    safety_check_id=assessment.check_id,
                    confirmed_safety_notice=True,
                )
            )
        stored = ManualMedicationAccessRepository().get_check(assessment.check_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.check_status, "CHECK_FAILED")
        self.assertEqual(adapter.calls, [])

    def test_unknown_expiry_is_check_failed_instead_of_claiming_the_medicine_expired(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.schemas.manual_medication_access import AssessManualMedicationCommand
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET expire_date='待核验' WHERE id='slot-14-oseltamivir'"
            )
        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )

        assessment = ManualMedicationAccessModule(
            identity_assertions=assertions,
        ).assess(
            AssessManualMedicationCommand(
                request_id="assess-unknown-expiry-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
            )
        )

        self.assertEqual(assessment.check_status, "CHECK_FAILED")
        self.assertEqual(assessment.reason_codes, ["MEDICINE_DATA_UNREVIEWED"])
        self.assertNotIn("已过有效期", assessment.message)
        self.assertIn("柜门未打开", assessment.message)

    def test_stock_change_invalidates_a_pass_before_the_dispense_boundary(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
            ManualDispenseExecutionResult,
        )
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> ManualDispenseExecutionResult:
                self.calls.append(command)
                return ManualDispenseExecutionResult(
                    dispense_status="DISPENSED",
                    message="柜门已打开。",
                )

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        dispense = RecordingDispenseAdapter()
        module = ManualMedicationAccessModule(
            identity_assertions=assertions,
            dispense_adapter=dispense,
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-stock-binding-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
            )
        )
        self.assertEqual(assessment.check_status, "PASSED")
        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET stock=stock+1 WHERE id=?",
                (medicine.id,),
            )

        with self.assertRaisesRegex(ValueError, "库存记录已经变化"):
            module.confirm(
                ConfirmManualMedicationCommand(
                    request_id="confirm-stock-binding-001",
                    safety_check_id=assessment.check_id,
                    confirmed_safety_notice=True,
                )
            )
        stored = ManualMedicationAccessRepository().get_check(assessment.check_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.check_status, "CHECK_FAILED")
        self.assertEqual(stored.dispense_status, "NOT_STARTED")
        self.assertEqual(
            ManualMedicationAccessRepository().count_outbox_events(
                check_id=assessment.check_id
            ),
            1,
        )
        self.assertEqual(dispense.calls, [])

    def test_hardware_slot_change_invalidates_a_pass_before_the_dispense_boundary(self) -> None:
        from app.repositories.identity_assertion_repository import IdentityAssertionRepository
        from app.repositories.manual_medication_access_repository import ManualMedicationAccessRepository
        from app.schemas.manual_medication_access import (
            AssessManualMedicationCommand,
            ConfirmManualMedicationCommand,
            ManualDispenseExecutionResult,
        )
        from app.services.manual_medication_access_module import ManualMedicationAccessModule

        class RecordingDispenseAdapter:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def confirm_manual(self, command: object) -> ManualDispenseExecutionResult:
                self.calls.append(command)
                return ManualDispenseExecutionResult(
                    dispense_status="DISPENSED",
                    message="柜门已打开。",
                )

        assertions = IdentityAssertionRepository()
        assertion = assertions.issue(
            service_user_id="li-yeye",
            verification_method="face",
        )
        medicine = MedicineRepository().get_by_id("slot-14-oseltamivir")
        self.assertIsNotNone(medicine)
        dispense = RecordingDispenseAdapter()
        module = ManualMedicationAccessModule(
            identity_assertions=assertions,
            dispense_adapter=dispense,
        )
        assessment = module.assess(
            AssessManualMedicationCommand(
                request_id="assess-hardware-slot-binding-001",
                medicine_id=medicine.id,
                slot=medicine.slot,
                service_user_id="li-yeye",
                verification_method="face",
                verification_assertion_id=assertion.assertion_id,
                expected_review_fingerprint=MedicineRepository.review_fingerprint(medicine),
            )
        )
        self.assertEqual(assessment.check_status, "PASSED")
        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET hardware_slot=23 WHERE id=?",
                (medicine.id,),
            )

        with self.assertRaisesRegex(ValueError, "仓位映射已经变化"):
            module.confirm(
                ConfirmManualMedicationCommand(
                    request_id="confirm-hardware-slot-binding-001",
                    safety_check_id=assessment.check_id,
                    confirmed_safety_notice=True,
                )
            )
        stored = ManualMedicationAccessRepository().get_check(assessment.check_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.check_status, "CHECK_FAILED")
        self.assertEqual(dispense.calls, [])

    def test_archived_demo_identity_is_not_rebound_or_given_an_assertion(self) -> None:
        from app.services.identity_service import IdentityService

        class ArchivedFaceClient:
            @staticmethod
            def identify() -> dict[str, object]:
                return {
                    "status": "matched",
                    "subject": "profile:zhangsan",
                    "confidence": 0.95,
                }

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status, archived
                ) VALUES ('zhangsan', '张三', 70, '历史演示人物', '', '', '已归档', 1)
                """
            )
        IdentityService._bind("profile:zhangsan", "zhangsan", 0.95)

        response = IdentityService(face_client=ArchivedFaceClient()).resolve()

        self.assertFalse(response.ok)
        self.assertEqual(response.status, "unbound")
        self.assertEqual(response.verification_assertion_id, "")

    def test_debug_dry_run_has_an_explicit_non_hardware_adapter(self) -> None:
        from app.schemas.dispense import DispenseConfirmRequest
        from app.services.dispense_service import DispenseService

        class RecordingQsm:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, bool]] = []

            def dispense(self, slot: str, quantity: int, *, dry_run: bool) -> dict[str, object]:
                self.calls.append((slot, quantity, dry_run))
                return {"ok": True, "detail": "dry run"}

        medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        qsm = RecordingQsm()
        service = DispenseService(qsm_client=qsm)

        response = service.confirm_debug_dry_run(
            DispenseConfirmRequest(
                medicine_id=medicine.id,
                slot=medicine.slot,
                quantity=1,
                reason="设备调试台干跑",
                confirmed_safety_notice=True,
                target_user_name="设备调试",
                verification_method="debug_dry_run",
            )
        )

        self.assertTrue(response.ok)
        self.assertTrue(response.dry_run)
        self.assertEqual(qsm.calls, [("17", 1, True)])


if __name__ == "__main__":
    unittest.main()
