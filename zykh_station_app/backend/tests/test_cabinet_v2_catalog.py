from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.repositories.medicine_repository import BUNDLED_LABEL_SAFETY_IDS  # noqa: E402
from app.schemas.medicine import Medicine, MedicineScanRegisterRequest  # noqa: E402
from app.services.cabinet_v2_catalog import (  # noqa: E402
    CabinetMappingError,
    cabinet_for_medicine_id,
    cabinet_groups,
    mapped_medicine_ids,
)
from app.services.medicine_scan_service import MedicineScanService  # noqa: E402
from app.services.medicine_service import MedicineService  # noqa: E402


class CabinetV2CatalogTest(unittest.TestCase):
    def test_local_catalog_exposes_three_named_cabinets_and_routes_known_examples(self) -> None:
        groups = cabinet_groups()

        self.assertEqual(
            [(group.id, group.label) for group in groups],
            [
                (1, "口服药品"),
                (2, "外用药品"),
                (3, "医疗护理用品"),
            ],
        )
        self.assertEqual(cabinet_for_medicine_id("slot-13-ibuprofen").id, 1)
        self.assertEqual(cabinet_for_medicine_id("slot-18-budesonide-nasal").id, 2)
        self.assertEqual(cabinet_for_medicine_id("slot-22-cotton-swab").id, 3)

    def test_every_bundled_medicine_has_one_explicit_local_cabinet_assignment(self) -> None:
        assigned_ids = [
            medicine_id
            for group in cabinet_groups()
            for medicine_id in group.medicine_ids
        ]

        self.assertEqual(len(assigned_ids), len(BUNDLED_LABEL_SAFETY_IDS))
        self.assertEqual(len(assigned_ids), len(set(assigned_ids)))
        self.assertEqual(mapped_medicine_ids(), BUNDLED_LABEL_SAFETY_IDS)

    def test_unknown_medicine_fails_closed_before_hardware_routing(self) -> None:
        with self.assertRaisesRegex(CabinetMappingError, "未配置分类柜"):
            cabinet_for_medicine_id("unknown-medicine")

    def test_scan_result_projects_a_known_medicine_to_its_local_cabinet(self) -> None:
        medicine = SimpleNamespace(
            id="slot-18-budesonide-nasal",
            name="布地奈德鼻喷雾剂",
            image_hint="64μg×120喷",
            stock=1,
            unit="盒",
            expire_date="2027-01",
            hardware_slot=18,
            slot="18",
        )
        repository = SimpleNamespace(get_by_barcode=lambda barcode: medicine)

        result = MedicineScanService(repository=repository).scan("12345678")

        self.assertTrue(result.ok)
        self.assertEqual(result.cabinet_id, 2)
        self.assertEqual(result.cabinet_label, "外用药品")
        # Retained only as a compatibility identity; the local UI does not render it.
        self.assertEqual(result.slot, "18")

    def test_scan_registration_returns_an_existing_barcode_without_creating_a_record(self) -> None:
        existing = Medicine(
            id="slot-01-fufang-ganmaoling",
            slot="S01",
            hardware_slot=1,
            barcode="690000000001",
            name="复方感冒灵颗粒",
            category="解热镇痛",
            tags=[],
            contraindications=[],
            stock=1,
            unit="盒",
            expire_date="2028-08",
            image_hint="",
            is_otc=True,
            is_emergency=False,
            safety_note="按说明使用。",
        )

        class ExistingOnlyRepository:
            create_called = False

            @staticmethod
            def get_by_barcode(barcode: str) -> Medicine | None:
                return existing if barcode == existing.barcode else None

            def create_from_scan(self, **_kwargs: object) -> Medicine:
                self.create_called = True
                raise AssertionError("existing barcode must not create a medicine")

        repository = ExistingOnlyRepository()
        service = MedicineService(
            repository=repository,
            guidance_service=SimpleNamespace(),
            dispense_repository=SimpleNamespace(successful_counts_by_medicine=lambda: {}),
        )

        result = service.register_scan_result(
            MedicineScanRegisterRequest(barcode=existing.barcode, name="不会覆盖现有名称")
        )

        self.assertTrue(result.ok)
        self.assertFalse(result.created)
        self.assertEqual(result.medicine.id, existing.id)
        self.assertEqual(result.medicine.cabinet_id, 1)
        self.assertEqual(result.medicine.cabinet_label, "口服药品")
        self.assertFalse(repository.create_called)

    def test_scan_registration_rejects_an_unknown_medicine_without_writing(self) -> None:
        class RejectingRepository:
            create_called = False

            @staticmethod
            def get_by_barcode(_barcode: str) -> None:
                return None

            def create_from_scan(self, **_kwargs: object) -> Medicine:
                self.create_called = True
                raise AssertionError("unknown medicines must not be created")

            @staticmethod
            def list_all() -> list[Medicine]:
                raise AssertionError("unknown registration must fail before slot allocation")

        repository = RejectingRepository()
        service = MedicineService(
            repository=repository,
            guidance_service=SimpleNamespace(),
            dispense_repository=SimpleNamespace(successful_counts_by_medicine=lambda: {}),
        )

        result = service.register_scan_result(
            MedicineScanRegisterRequest(
                barcode="new-unmapped-barcode",
                name="未知新药",
                slot=1,
            )
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.created)
        self.assertIsNone(result.medicine)
        self.assertIn("不自动新建未映射药品", result.message)
        self.assertFalse(repository.create_called)


if __name__ == "__main__":
    unittest.main()
