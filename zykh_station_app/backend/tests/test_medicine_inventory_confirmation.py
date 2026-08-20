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
from app.repositories.dispense_repository import DispenseRepository  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.schemas.dispense import DispenseRecord  # noqa: E402
from app.schemas.medicine import MedicineInventoryConfirmationRequest  # noqa: E402
from app.services.cloud_sync_service import CloudSyncWorker  # noqa: E402
from app.services.medicine_inventory_confirmation import (  # noqa: E402
    MedicineInventoryConfirmationConflictError,
    MedicineInventoryConfirmationModule,
)


class MedicineInventoryConfirmationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "inventory-confirmation.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        self.medicine = MedicineRepository().get_by_id("slot-17-iodophor")
        assert self.medicine is not None

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def successful_dispense(
        self,
        record_id: str = "dispense-inventory-001",
        *,
        stock_after: int | None = None,
        bind_observation: bool = True,
    ) -> DispenseRecord:
        repository = MedicineRepository()
        if stock_after is not None:
            repository.update(self.medicine.id, {"stock": stock_after})
        record = DispenseRecord(
            id=record_id,
            medicine_id=self.medicine.id,
            medicine_name=self.medicine.name,
            slot=self.medicine.slot,
            hardware_slot=self.medicine.hardware_slot,
            quantity=1,
            unit=self.medicine.unit,
            reason="个人用药安全核查通过",
            dry_run=False,
            message="柜门已打开",
            qsm_ok=True,
            target_user_id="wang-nainai",
            target_user_name="王奶奶",
            verification_method="face",
            created_at="2026-08-10 20:00:00",
        )
        saved = DispenseRepository().append(record)
        if not bind_observation:
            return saved
        token = repository.get_inventory_observation_token(self.medicine.id)
        assert token is not None
        self.assertTrue(
            repository.mark_inventory_observation_pending(
                self.medicine.id,
                saved.id,
                expected_stock=token.stock,
                expected_inventory_revision=token.revision,
            )
        )
        return saved

    def test_late_older_dispense_cannot_replace_the_latest_pending_observation(self) -> None:
        repository = MedicineRepository()
        token = repository.get_inventory_observation_token(self.medicine.id)
        assert token is not None
        older = self.successful_dispense(
            "dispense-inventory-interleaved-older",
            bind_observation=False,
        )
        latest = self.successful_dispense(
            "dispense-inventory-interleaved-latest",
            bind_observation=False,
        )

        self.assertTrue(
            repository.mark_inventory_observation_pending(
                self.medicine.id,
                latest.id,
                expected_stock=token.stock,
                expected_inventory_revision=token.revision,
            )
        )
        self.assertFalse(
            repository.mark_inventory_observation_pending(
                self.medicine.id,
                older.id,
                expected_stock=token.stock,
                expected_inventory_revision=token.revision,
            )
        )
        refreshed = repository.get_by_id(self.medicine.id)
        assert refreshed is not None
        self.assertEqual(refreshed.stock, 1)
        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, latest.id)

    def test_has_remaining_restores_a_minimum_truth_after_the_last_physical_dispense(self) -> None:
        record = self.successful_dispense(stock_after=0)
        repository = MedicineRepository()
        self.assertTrue(repository.inventory_confirmation_required(record.id))

        response = MedicineInventoryConfirmationModule().confirm(
            self.medicine.id,
            MedicineInventoryConfirmationRequest(
                request_id="inventory-confirm-001",
                dispense_record_id=record.id,
                observation="HAS_REMAINING",
            ),
        )

        self.assertTrue(response.ok)
        self.assertFalse(response.replayed)
        self.assertEqual(response.stock, 1)
        self.assertEqual(response.inventory_state, "AVAILABLE")
        refreshed = MedicineRepository().get_by_id(self.medicine.id)
        assert refreshed is not None
        self.assertEqual(refreshed.stock, 1)
        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.last_inventory_request_id, "inventory-confirm-001")
        self.assertFalse(repository.inventory_confirmation_required(record.id))
        cloud_row = next(
            row
            for row in CloudSyncWorker._build_snapshot()["medicines"]
            if row["id"] == self.medicine.id
        )
        self.assertEqual(cloud_row["quantity"], 1)
        self.assertEqual(cloud_row["inventoryState"], "STOCKED")
        self.assertTrue(cloud_row["inventoryConfirmedAt"])

    def test_depleted_confirmation_is_idempotent_and_cannot_be_rewritten(self) -> None:
        record = self.successful_dispense(
            "dispense-inventory-depleted",
            stock_after=0,
        )
        module = MedicineInventoryConfirmationModule()
        request = MedicineInventoryConfirmationRequest(
            request_id="inventory-confirm-depleted-001",
            dispense_record_id=record.id,
            observation="DEPLETED",
        )

        first = module.confirm(self.medicine.id, request)
        replay = module.confirm(self.medicine.id, request)

        self.assertEqual(first.inventory_state, "DEPLETED")
        self.assertEqual(first.stock, 0)
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.inventory_confirmed_at, first.inventory_confirmed_at)
        cloud_row = next(
            row
            for row in CloudSyncWorker._build_snapshot()["medicines"]
            if row["id"] == self.medicine.id
        )
        self.assertEqual(cloud_row["depletionConfirmedAt"], first.inventory_confirmed_at)
        self.assertEqual(cloud_row["depletion_confirmed_at"], first.inventory_confirmed_at)
        self.assertEqual(cloud_row["depletionConfirmationSource"], "ON_DEVICE_CONFIRMATION")
        self.assertEqual(cloud_row["depletion_confirmation_source"], "ON_DEVICE_CONFIRMATION")
        with self.assertRaises(MedicineInventoryConfirmationConflictError):
            module.confirm(
                self.medicine.id,
                request.model_copy(update={"observation": "HAS_REMAINING"}),
            )

    def test_old_dispense_record_cannot_overwrite_a_newer_inventory_truth(self) -> None:
        old_record = self.successful_dispense("dispense-inventory-old")
        self.successful_dispense("dispense-inventory-new")

        with self.assertRaises(MedicineInventoryConfirmationConflictError):
            MedicineInventoryConfirmationModule().confirm(
                self.medicine.id,
                MedicineInventoryConfirmationRequest(
                    request_id="inventory-confirm-stale-001",
                    dispense_record_id=old_record.id,
                    observation="HAS_REMAINING",
                ),
            )

    def test_admin_stock_update_invalidates_the_pending_physical_observation(self) -> None:
        record = self.successful_dispense("dispense-inventory-before-admin")
        repository = MedicineRepository()

        updated = repository.update(
            self.medicine.id,
            {"stock": self.medicine.stock + 2},
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.inventory_state, "AVAILABLE")
        self.assertEqual(updated.last_inventory_dispense_record_id, "")

        with self.assertRaises(MedicineInventoryConfirmationConflictError):
            MedicineInventoryConfirmationModule().confirm(
                self.medicine.id,
                MedicineInventoryConfirmationRequest(
                    request_id="inventory-confirm-after-admin",
                    dispense_record_id=record.id,
                    observation="HAS_REMAINING",
                ),
            )

    def test_medicine_identity_replacement_invalidates_the_old_pending_observation(self) -> None:
        record = self.successful_dispense("dispense-inventory-before-replacement")
        repository = MedicineRepository()

        replacement = repository.update(
            self.medicine.id,
            {"name": "同仓位更换后的新药品"},
        )

        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.inventory_state, "AVAILABLE")
        self.assertEqual(replacement.last_inventory_request_id, "")
        self.assertEqual(replacement.last_inventory_dispense_record_id, "")
        with self.assertRaises(MedicineInventoryConfirmationConflictError):
            MedicineInventoryConfirmationModule().confirm(
                self.medicine.id,
                MedicineInventoryConfirmationRequest(
                    request_id="inventory-confirm-after-replacement",
                    dispense_record_id=record.id,
                    observation="HAS_REMAINING",
                ),
            )

    def test_scan_upsert_invalidates_a_pending_observation_for_the_same_row(self) -> None:
        repository = MedicineRepository()
        scanned = repository.create_from_scan(
            barcode="scan-upsert-inventory",
            name="扫码库存测试药",
            hardware_slot=24,
            stock=2,
            deduplicate_barcode=False,
        )
        record = DispenseRepository().append(
            DispenseRecord(
                id="dispense-before-scan-upsert",
                medicine_id=scanned.id,
                medicine_name=scanned.name,
                slot=scanned.slot,
                hardware_slot=scanned.hardware_slot,
                quantity=1,
                unit=scanned.unit,
                reason="扫码更新前开柜",
                dry_run=False,
                message="柜门已打开",
                qsm_ok=True,
                target_user_id="wang-nainai",
                target_user_name="王奶奶",
                verification_method="face",
                created_at="2026-08-10 20:00:01",
            )
        )
        token = repository.get_inventory_observation_token(scanned.id)
        assert token is not None
        self.assertTrue(
            repository.mark_inventory_observation_pending(
                scanned.id,
                record.id,
                expected_stock=token.stock,
                expected_inventory_revision=token.revision,
            )
        )

        upserted = repository.create_from_scan(
            barcode="scan-upsert-inventory",
            name="扫码库存测试药",
            hardware_slot=24,
            stock=5,
            deduplicate_barcode=False,
        )

        self.assertEqual(upserted.id, scanned.id)
        self.assertEqual(upserted.stock, 5)
        self.assertEqual(upserted.inventory_state, "AVAILABLE")
        self.assertEqual(upserted.last_inventory_dispense_record_id, "")
        with self.assertRaises(MedicineInventoryConfirmationConflictError):
            MedicineInventoryConfirmationModule().confirm(
                scanned.id,
                MedicineInventoryConfirmationRequest(
                    request_id="inventory-confirm-after-scan-upsert",
                    dispense_record_id=record.id,
                    observation="HAS_REMAINING",
                ),
            )

    def test_cloud_stock_patch_invalidates_the_pending_physical_observation(self) -> None:
        record = self.successful_dispense("dispense-inventory-before-cloud")

        CloudSyncWorker._upsert_medicine(
            {
                "operation": "patch",
                "hardware_slot": self.medicine.hardware_slot,
                "patch": {"quantity": self.medicine.stock + 3},
            }
        )

        refreshed = MedicineRepository().get_by_id(self.medicine.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.inventory_state, "AVAILABLE")
        self.assertEqual(refreshed.last_inventory_dispense_record_id, "")
        with self.assertRaises(MedicineInventoryConfirmationConflictError):
            MedicineInventoryConfirmationModule().confirm(
                self.medicine.id,
                MedicineInventoryConfirmationRequest(
                    request_id="inventory-confirm-after-cloud",
                    dispense_record_id=record.id,
                    observation="HAS_REMAINING",
                ),
            )


if __name__ == "__main__":
    unittest.main()
