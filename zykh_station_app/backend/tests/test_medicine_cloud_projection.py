from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.cabinet_v2_catalog import cabinet_for_medicine_id  # noqa: E402
from app.repositories.medicine_repository import BUNDLED_LABEL_SAFETY_IDS  # noqa: E402
from app.services.medicine_cloud_projection import (  # noqa: E402
    MedicineCloudProjectionError,
    cloud_projection_for_local_medicine_id,
    medicine_cloud_projections,
    resolve_cloud_medicine,
    validate_local_medicine_catalog,
)


class MedicineCloudProjectionTest(unittest.TestCase):
    def test_fixed_catalog_has_one_complete_bijective_projection(self) -> None:
        projections = medicine_cloud_projections()

        self.assertEqual(len(projections), 23)
        self.assertEqual(len({item.local_medicine_id for item in projections}), 23)
        self.assertEqual(len({item.local_legacy_slot for item in projections}), 23)
        self.assertEqual(len({item.cloud_medicine_id for item in projections}), 23)
        self.assertEqual(len({item.cloud_legacy_slot for item in projections}), 23)
        self.assertEqual(
            {item.local_medicine_id for item in projections},
            BUNDLED_LABEL_SAFETY_IDS,
        )
        self.assertEqual(
            Counter(item.storage_box for item in projections),
            {"DAILY": 9, "CARE": 8, "PRESCRIPTION": 6},
        )
        self.assertEqual(
            {
                storage_box: {
                    item.local_legacy_slot
                    for item in projections
                    if item.storage_box == storage_box
                }
                for storage_box in ("DAILY", "CARE", "PRESCRIPTION")
            },
            {
                "DAILY": {1, 3, 5, 7, 8, 11, 12, 13, 23},
                "CARE": {10, 15, 16, 17, 18, 19, 20, 22},
                "PRESCRIPTION": {2, 4, 6, 9, 14, 21},
            },
        )

    def test_s09_keeps_stable_identity_and_prescription_projection(self) -> None:
        probiotic = cloud_projection_for_local_medicine_id("slot-09-bifid-triple")

        self.assertEqual(cabinet_for_medicine_id(probiotic.local_medicine_id).id, 3)
        self.assertEqual(probiotic.storage_box, "PRESCRIPTION")
        self.assertEqual(probiotic.cloud_medicine_id, "slot-09-bifid-triple")
        self.assertEqual(probiotic.cloud_legacy_slot, 9)

    def test_projection_adapts_the_two_different_catalog_identities(self) -> None:
        montmorillonite = cloud_projection_for_local_medicine_id("slot-03-diosmectite")
        ibuprofen = cloud_projection_for_local_medicine_id("slot-13-ibuprofen")

        self.assertEqual(
            (montmorillonite.cloud_medicine_id, montmorillonite.cloud_legacy_slot),
            ("slot-13-montmorillonite", 13),
        )
        self.assertEqual(
            (ibuprofen.cloud_medicine_id, ibuprofen.cloud_legacy_slot),
            ("slot-03-ibuprofen", 3),
        )
        self.assertEqual(resolve_cloud_medicine(legacy_slot=3), ibuprofen)
        self.assertEqual(
            resolve_cloud_medicine(medicine_id="slot-13-montmorillonite"),
            montmorillonite,
        )

    def test_conflicting_cloud_identity_and_slot_fail_closed(self) -> None:
        with self.assertRaisesRegex(MedicineCloudProjectionError, "身份与兼容仓位不一致"):
            resolve_cloud_medicine(
                medicine_id="slot-03-ibuprofen",
                legacy_slot=13,
            )

    def test_unknown_local_or_cloud_identity_fails_closed(self) -> None:
        with self.assertRaisesRegex(MedicineCloudProjectionError, "未配置小程序同步投影"):
            cloud_projection_for_local_medicine_id("unknown-medicine")
        with self.assertRaisesRegex(MedicineCloudProjectionError, "无法识别云端药品身份"):
            resolve_cloud_medicine(medicine_id="unknown-medicine")

    def test_local_catalog_validation_requires_every_exact_identity_slot_pair(self) -> None:
        exact_catalog = [
            (item.local_medicine_id, item.local_legacy_slot)
            for item in medicine_cloud_projections()
        ]

        validate_local_medicine_catalog(exact_catalog)

        with self.assertRaisesRegex(
            MedicineCloudProjectionError,
            "本地固定药品目录.*不完整",
        ):
            validate_local_medicine_catalog(exact_catalog[:-1])
        with self.assertRaisesRegex(
            MedicineCloudProjectionError,
            "身份或兼容仓位错位",
        ):
            validate_local_medicine_catalog(
                [*exact_catalog[:-1], (exact_catalog[-1][0], 99)]
            )


if __name__ == "__main__":
    unittest.main()
