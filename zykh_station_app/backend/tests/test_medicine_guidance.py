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
from app.repositories.medicine_repository import (  # noqa: E402
    MEDICINE_GUIDANCE_VERSION,
    MedicineRepository,
)
from app.schemas.medicine import MedicineUpdateRequest  # noqa: E402
from app.services.medicine_service import MedicineService  # noqa: E402


class StubGuidanceService:
    def __init__(self, repository: MedicineRepository) -> None:
        self.repository = repository
        self.calls: list[str] = []

    def enrich_medicine(self, medicine_id: str):
        self.calls.append(medicine_id)
        return self.repository.update(
            medicine_id,
            {
                "indications": "结构化适用症状",
                "dosage": "按实物包装说明书使用",
                "contraindications": ["结构化禁忌提醒"],
                "guidance_source": "cloud_ai",
                "guidance_review_required": True,
                "guidance_updated_at": db.now_text(),
            },
        )


class MedicineGuidanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "medicine.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        self.repository = MedicineRepository()
        self.guidance = StubGuidanceService(self.repository)
        self.service = MedicineService(self.repository, self.guidance)

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_all_seeded_medicines_have_structured_guidance(self) -> None:
        medicines = self.service.list_medicines().medicines

        self.assertEqual(len(medicines), 23)
        self.assertTrue(all(item.indications for item in medicines))
        self.assertTrue(all(item.dosage for item in medicines))
        self.assertTrue(all(item.contraindications for item in medicines))
        self.assertTrue(all(item.guidance_source == "label_reference" for item in medicines))
        self.assertFalse(any("按当前包装说明书" in item.dosage for item in medicines))

    def test_guidance_version_migrates_fixed_reference_without_resetting_inventory(self) -> None:
        self.service.list_medicines()
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET stock=7, indications='暑湿不适、腹胀呕吐', dosage='请按包装说明书使用'
                WHERE id='slot-08-huoxiang-zhengqi'
                """
            )
            conn.execute("DELETE FROM app_settings WHERE key='medicine_guidance_version'")

        medicine = self.service.get_medicine("slot-08-huoxiang-zhengqi")

        self.assertEqual(medicine.stock, 7)
        self.assertEqual(
            medicine.indications,
            "解表化湿，理气和中。用于暑湿感冒，头痛身重胸闷，或恶寒发热，脘腹胀痛，呕吐泄泻。",
        )
        self.assertEqual(medicine.dosage, "口服，一次1丸，一日2次。")
        self.assertEqual(medicine.guidance_source, "label_reference")
        with db.connect() as conn:
            version = conn.execute(
                "SELECT value FROM app_settings WHERE key='medicine_guidance_version'"
            ).fetchone()
        self.assertEqual(version["value"], MEDICINE_GUIDANCE_VERSION)

    def test_guidance_migration_does_not_overwrite_renamed_admin_medicine(self) -> None:
        self.service.list_medicines()
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET name='家庭自备藿香正气丸', indications='管理员确认的适用说明',
                    dosage='管理员确认的用量'
                WHERE id='slot-08-huoxiang-zhengqi'
                """
            )
            conn.execute("DELETE FROM app_settings WHERE key='medicine_guidance_version'")

        medicine = self.service.get_medicine("slot-08-huoxiang-zhengqi")

        self.assertEqual(medicine.name, "家庭自备藿香正气丸")
        self.assertEqual(medicine.indications, "管理员确认的适用说明")
        self.assertEqual(medicine.dosage, "管理员确认的用量")

    def test_base_information_change_refreshes_guidance(self) -> None:
        medicine = self.service.get_medicine("slot-08-huoxiang-zhengqi")
        result = self.service.update_medicine(
            medicine.id,
            MedicineUpdateRequest(name="藿香正气丸（新包装）"),
        )

        self.assertEqual(self.guidance.calls, [medicine.id])
        self.assertEqual(result.medicine.guidance_source, "cloud_ai")
        self.assertEqual(result.medicine.indications, "结构化适用症状")

    def test_stock_change_does_not_refresh_guidance(self) -> None:
        medicine = self.service.get_medicine("slot-08-huoxiang-zhengqi")
        result = self.service.update_medicine(medicine.id, MedicineUpdateRequest(stock=4))

        self.assertEqual(self.guidance.calls, [])
        self.assertEqual(result.medicine.stock, 4)


if __name__ == "__main__":
    unittest.main()
