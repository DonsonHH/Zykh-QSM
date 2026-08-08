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
from app.services.medicine_guidance_service import MedicineGuidanceService  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
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


class StubSafetyFactsAiService:
    def generate_medicine_guidance(self, _medicine):
        return {
            "ok": True,
            "guidance": {
                "indications": "用于测试症状",
                "dosage": "按实物包装说明书使用",
                "contraindications": ["测试辅料过敏者禁用"],
                "aliases": ["动态品牌名", "动态通用名"],
                "active_ingredients": ["动态有效成分"],
                "structured_contraindications": [
                    {
                        "concept_code": "ingredient_allergy",
                        "display_text": "测试辅料过敏者禁用",
                    }
                ],
                "safety_note": "资料待药师核验",
            },
        }


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
        sources = {item.id: item.guidance_source for item in medicines}
        self.assertEqual({source for source in sources.values()}, {"label_reference"})
        self.assertFalse(any("按当前包装说明书" in item.dosage for item in medicines))

    def test_contraindications_are_not_mixed_into_dosage_instructions(self) -> None:
        medicines = {item.id: item for item in self.service.list_medicines().medicines}
        cough_syrup = medicines["slot-05-nin-jiom-pei-pa-koa"]
        cold_granules = medicines["slot-01-fufang-ganmaoling"]

        self.assertEqual(cough_syrup.dosage, "口服，成人每日3次，每次1汤匙（15毫升）；儿童酌减。")
        self.assertIn("糖尿病患者禁用", cough_syrup.contraindications)
        self.assertNotIn("禁用", cough_syrup.dosage)
        self.assertNotIn("勿与同类感冒药重复使用", cold_granules.dosage)
        self.assertTrue(any("重复使用" in item for item in cold_granules.contraindications))

    def test_cold_granules_keep_guidance_sections_separate(self) -> None:
        medicine = self.service.get_medicine("slot-01-fufang-ganmaoling")

        self.assertEqual(
            medicine.indications,
            "辛凉解表，清热解毒。用于风热感冒之发热，微恶风寒，头身痛，口干而渴，鼻塞涕浊，咽喉红肿疼痛，咳嗽，痰黄粘稠。",
        )
        self.assertEqual(medicine.dosage, "开水冲服，一次14克，一日3次；2天为一疗程。")
        self.assertEqual(
            medicine.contraindications,
            ["严重肝肾功能不全禁用", "避免与同类解热镇痛药重复使用"],
        )

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
        self.assertFalse(result.medicine.package_verified)

    def test_stock_change_does_not_refresh_guidance(self) -> None:
        medicine = self.service.get_medicine("slot-08-huoxiang-zhengqi")
        result = self.service.update_medicine(medicine.id, MedicineUpdateRequest(stock=4))

        self.assertEqual(self.guidance.calls, [])
        self.assertEqual(result.medicine.stock, 4)

    def test_dynamic_scan_enrichment_persists_safety_facts_as_unreviewed_draft(self) -> None:
        scanned = self.repository.create_from_scan(
            barcode="dynamic-guidance-barcode",
            manufacturer="动态厂家",
            name="动态扫码药品",
            spec="测试规格",
            expire_date="2030-12",
            hardware_slot=24,
        )
        guidance = MedicineGuidanceService(
            repository=self.repository,
            ai_service=StubSafetyFactsAiService(),
        )

        enriched = guidance.enrich_medicine(scanned.id)
        persisted = self.repository.get_by_id(scanned.id)

        self.assertEqual(enriched.aliases, ["动态品牌名", "动态通用名"])
        self.assertEqual(persisted.active_ingredients, ["动态有效成分"])
        self.assertEqual(
            persisted.structured_contraindications,
            [
                {
                    "concept_code": "ingredient_allergy",
                    "display_text": "测试辅料过敏者禁用",
                }
            ],
        )
        self.assertEqual(persisted.safety_review_status, "draft")
        self.assertEqual(persisted.safety_reviewed_by, "")
        self.assertEqual(persisted.safety_reviewed_at, "")
        self.assertNotIn(
            persisted.id,
            {item.id for item in MedicineKnowledgeRepository(self.repository).safe_candidate_pool("")},
        )


if __name__ == "__main__":
    unittest.main()
