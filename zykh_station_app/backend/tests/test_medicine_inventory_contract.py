from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.routers.medicines import list_medicines  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.schemas.records import TodayPlanCreateRequest  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class MedicineInventoryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "medicine-inventory.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_public_inventory_exposes_all_23_physical_slots_in_order(self) -> None:
        response = list_medicines()

        self.assertEqual(response.total, 23)
        self.assertEqual(response.warehouse_total, 23)
        self.assertEqual([item.hardware_slot for item in response.medicines], list(range(1, 24)))
        expected_names = (
            "复方感冒灵颗粒", "多维元素片", "蒙脱石散", "阿莫西林胶囊",
            "蜜炼川贝枇杷膏", "乳果糖口服液", "银黄颗粒", "藿香正气丸",
            "双歧杆菌三联活菌肠溶胶囊", "医用纱布敷料", "桂林西瓜霜",
            "铝碳酸镁咀嚼片", "布洛芬缓释胶囊", "磷酸奥司他韦胶囊", "莫匹罗星软膏",
            "酮康唑乳膏", "碘伏消毒液", "布地奈德鼻喷雾剂", "酮洛芬凝胶",
            "创口贴", "苯磺酸氨氯地平片", "医用棉签", "枸地氯雷他定胶囊",
        )
        self.assertEqual(tuple(item.name for item in response.medicines), expected_names)

    def test_known_package_fields_match_the_physical_inventory(self) -> None:
        medicines = {item.hardware_slot: item for item in list_medicines().medicines}

        expected = {
            1: ("999", "6900966688219", "2026-12"),
            2: ("善存", "", "2027-09-18"),
            3: ("博福-益普生（天津）制药有限公司", "6932833600109", "2030-02"),
            4: ("华北制药", "6938588802331", "2027-02"),
            5: ("京都念慈庵", "081364361693", "2028-06"),
            6: ("健能药业", "6943798800923", "2027-02"),
            7: ("神鹤药业", "6934199500017", "2028-08-29"),
            8: ("恒心堂", "6921711516168", "2028-03"),
            9: ("贝飞达", "6922313021210", "2026-09"),
            10: ("可孚", "6950715511633", "2026-11-12"),
            11: ("三金", "6939261900771", "2028-01-08"),
            12: ("华森制药", "6921041723526", "2027-08"),
            13: ("中美天津史克制药有限公司", "6913991301572", "2029-01"),
            14: ("华海药业", "6958439003076", "2028-11"),
            15: ("中美史克", "62000000204025", "2026-02"),
            16: ("金日制药", "", "2028-09-30"),
            17: ("利尔康", "6926378900350", "2026-12-10"),
            18: ("雷诺考特", "", "2027-01"),
            19: ("法斯通", "", "2028-08"),
            20: ("凡卡", "", "2026-11"),
            21: ("京新药业", "6910853810272", "2028-08"),
            22: ("稳健医疗", "6932593000577", "2027-12"),
            23: ("恩瑞特医疗", "6970847150012", "2026-10-16"),
        }
        for slot, package_fields in expected.items():
            with self.subTest(slot=slot):
                medicine = medicines[slot]
                self.assertEqual(
                    (medicine.manufacturer, medicine.barcode, medicine.expire_date),
                    package_fields,
                )

    def test_replacements_expose_the_online_verified_barcode_identity(self) -> None:
        medicines = {item.hardware_slot: item for item in list_medicines().medicines}

        for slot, medicine_id in ((3, "slot-03-diosmectite"), (13, "slot-13-ibuprofen")):
            with self.subTest(slot=slot):
                medicine = medicines[slot]
                self.assertEqual(medicine.id, medicine_id)
                self.assertEqual(medicine.guidance_source, "label_reference")
                self.assertTrue(medicine.guidance_review_required)
                self.assertTrue(medicine.package_verified)

        safe_ids = {
            item.id
            for item in MedicineKnowledgeRepository().safe_candidate_pool("")
        }
        self.assertIn("slot-03-diosmectite", safe_ids)
        self.assertIn("slot-13-ibuprofen", safe_ids)

    def test_inventory_upgrade_replaces_only_the_two_changed_slots(self) -> None:
        repository = MedicineRepository()
        repository.list_all()
        repository.update(
            "slot-08-huoxiang-zhengqi",
            {"manufacturer": "管理员核验厂家", "stock": 7},
        )
        scanned = repository.create_from_scan(
            barcode="custom-scan-001",
            manufacturer="现场录入",
            name="管理员扫码药品",
            hardware_slot=24,
        )
        records = RecordsService()
        slot_3_plan = records.create_today_plan(TodayPlanCreateRequest(
            time="10:30",
            medicine_id="slot-03-diosmectite",
            service_user_id="zhangsan",
        ))
        slot_13_plan = records.create_today_plan(TodayPlanCreateRequest(
            time="11:30",
            medicine_id="slot-13-ibuprofen",
            service_user_id="zhangsan",
        ))
        preserved_plan = records.create_today_plan(TodayPlanCreateRequest(
            time="12:30",
            medicine_id="slot-08-huoxiang-zhengqi",
            service_user_id="zhangsan",
        ))

        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET id='slot-03-ganmao-qingre', name='感冒清热颗粒', "
                "barcode='6928849913616', manufacturer='999', category='感冒发热', "
                "tags_json='[\"风寒感冒\", \"头痛发热\"]', "
                "indications='疏风散寒，解表清热。用于风寒感冒，头痛发热，恶寒身痛，鼻流清涕，咳嗽咽干。', "
                "dosage='开水冲服，一次1袋（12克），一日2次。', "
                "contraindications_json='[\"对本品成分过敏禁用\", \"风热感冒表现者不适用\"]', "
                "stock=1, unit='盒', expire_date='2027-11', image_hint='999 感冒清热颗粒', "
                "is_otc=1, is_emergency=0, "
                "safety_note='用于风寒感冒相关症状，症状不匹配或持续加重需联系医生。' "
                "WHERE id='slot-03-diosmectite'"
            )
            conn.execute(
                "UPDATE medicines SET id='slot-13-sodium-hyaluronate-eye', name='玻璃酸钠滴眼液', "
                "barcode='6955236613620', manufacturer='普润盈', category='眼部护理', "
                "tags_json='[\"干眼\", \"眼部润滑\"]', "
                "indications='用于伴随干燥综合征、斯约二氏综合征等内因性疾患，或手术、药物、外伤、佩戴隐形眼镜等外因性疾患所致的角结膜上皮损伤。', "
                "dosage='滴眼，一次1滴，一日3次；可根据症状适当增减。', "
                "contraindications_json='[\"对成分过敏禁用\", \"瓶口勿接触眼部或皮肤\"]', "
                "stock=1, unit='盒', expire_date='2026-08-10', image_hint='普润盈玻璃酸钠滴眼液', "
                "is_otc=1, is_emergency=0, "
                "safety_note='眼部疼痛、红肿或视力变化时不要自行处理。' "
                "WHERE id='slot-13-ibuprofen'"
            )
            conn.execute(
                "UPDATE today_plans SET medicine_id='slot-03-ganmao-qingre', medicine='感冒清热颗粒' "
                "WHERE id=?",
                (slot_3_plan.id,),
            )
            conn.execute(
                "UPDATE today_plans SET medicine_id='slot-13-sodium-hyaluronate-eye', medicine='玻璃酸钠滴眼液' "
                "WHERE id=?",
                (slot_13_plan.id,),
            )
            conn.execute(
                "UPDATE app_settings SET value='home-real-cabinet-v4' "
                "WHERE key='medicine_seed_version'"
            )

        upgraded = {item.id: item for item in repository.list_all()}
        plans = {item.id: item for item in records.list_today_plans(due_only=False)}

        self.assertEqual(upgraded["slot-08-huoxiang-zhengqi"].manufacturer, "管理员核验厂家")
        self.assertEqual(upgraded["slot-08-huoxiang-zhengqi"].stock, 7)
        self.assertEqual(upgraded[scanned.id].name, "管理员扫码药品")
        self.assertNotIn("slot-03-ganmao-qingre", upgraded)
        self.assertNotIn("slot-13-sodium-hyaluronate-eye", upgraded)
        self.assertNotIn(slot_3_plan.id, plans)
        self.assertNotIn(slot_13_plan.id, plans)
        self.assertEqual(plans[preserved_plan.id].medicine_id, "slot-08-huoxiang-zhengqi")

    def test_inventory_upgrade_does_not_overwrite_an_admin_maintained_replacement(self) -> None:
        repository = MedicineRepository()
        repository.list_all()
        repository.update(
            "slot-03-diosmectite",
            {
                "manufacturer": "管理员现场核验厂家",
                "barcode": "admin-barcode-03",
                "expire_date": "2031-06",
            },
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE app_settings SET value='home-real-cabinet-v5-slot-03-13-replacements' "
                "WHERE key='medicine_seed_version'"
            )

        upgraded = repository.get_by_id("slot-03-diosmectite")

        self.assertEqual(upgraded.manufacturer, "管理员现场核验厂家")
        self.assertEqual(upgraded.barcode, "admin-barcode-03")
        self.assertEqual(upgraded.expire_date, "2031-06")

    def test_inventory_upgrade_promotes_the_exact_v6_user_identity_to_online_identity(self) -> None:
        repository = MedicineRepository()
        repository.list_all()
        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET manufacturer='迈优力制药', package_verified=0, "
                "guidance_source='pending' WHERE id='slot-03-diosmectite'"
            )
            conn.execute(
                "UPDATE medicines SET manufacturer='芬必得', package_verified=0, "
                "guidance_source='pending' WHERE id='slot-13-ibuprofen'"
            )
            conn.execute(
                "UPDATE app_settings SET value='home-real-cabinet-v6-slot-03-13-packages' "
                "WHERE key='medicine_seed_version'"
            )

        medicines = {item.id: item for item in repository.list_all()}

        self.assertEqual(
            medicines["slot-03-diosmectite"].manufacturer,
            "博福-益普生（天津）制药有限公司",
        )
        self.assertEqual(
            medicines["slot-13-ibuprofen"].manufacturer,
            "中美天津史克制药有限公司",
        )
        self.assertTrue(medicines["slot-03-diosmectite"].package_verified)
        self.assertTrue(medicines["slot-13-ibuprofen"].package_verified)

    def test_inventory_upgrade_does_not_replace_an_admin_modified_old_id(self) -> None:
        repository = MedicineRepository()
        repository.list_all()
        with db.connect() as conn:
            conn.execute(
                "UPDATE medicines SET id='slot-03-ganmao-qingre', name='现场保留药品', "
                "manufacturer='管理员核验厂家', barcode='admin-old-03' "
                "WHERE id='slot-03-diosmectite'"
            )
            conn.execute(
                "UPDATE app_settings SET value='home-real-cabinet-v4' "
                "WHERE key='medicine_seed_version'"
            )

        medicines = {item.id: item for item in repository.list_all()}

        self.assertEqual(medicines["slot-03-ganmao-qingre"].name, "现场保留药品")
        self.assertNotIn("slot-03-diosmectite", medicines)

    def test_expiry_uses_exact_day_when_the_package_includes_one(self) -> None:
        reference = date(2026, 8, 5)

        self.assertFalse(MedicineKnowledgeRepository.is_expired("2026-08", reference))
        self.assertTrue(MedicineKnowledgeRepository.is_expired("2026-08-01", reference))
        self.assertFalse(MedicineKnowledgeRepository.is_expired("2026-08-05", reference))
        self.assertFalse(MedicineKnowledgeRepository.is_expired("2026.08.06", reference))
        self.assertTrue(MedicineKnowledgeRepository.is_expired("2026-02-30", reference))

    def test_package_verification_upgrade_whitelists_fixed_identity_but_not_scans(self) -> None:
        repository = MedicineRepository()
        repository.list_all()
        scanned = repository.create_from_scan(
            barcode="legacy-cloud-scan",
            name="旧版云端补全药品",
            hardware_slot=24,
        )
        repository.update(scanned.id, {"guidance_source": "cloud_ai"})
        with db.connect() as conn:
            conn.execute("DELETE FROM app_settings WHERE key='package_verification_version'")
            column = next(
                row for row in conn.execute("PRAGMA table_info(medicines)").fetchall()
                if row["name"] == "package_verified"
            )

        medicines = {item.id: item for item in repository.list_all()}

        self.assertEqual(str(column["dflt_value"]).strip("'\""), "0")
        self.assertTrue(medicines["slot-08-huoxiang-zhengqi"].package_verified)
        self.assertFalse(medicines[scanned.id].package_verified)

    def test_allergy_matching_understands_natural_history_phrases(self) -> None:
        medicine = MedicineRepository().get_by_id("slot-04-amoxicillin")
        self.assertIsNotNone(medicine)

        for phrase in (
            "对青霉素过敏",
            "有青霉素过敏史",
            "本人曾有青霉素类药物不耐受史",
            "头孢和青霉素过敏",
            "青霉素类药物我不能用",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(MedicineKnowledgeRepository.has_allergy_conflict(medicine, phrase))
        self.assertFalse(MedicineKnowledgeRepository.has_allergy_conflict(medicine, "没有青霉素过敏"))


if __name__ == "__main__":
    unittest.main()
