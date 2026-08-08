from __future__ import annotations

import json
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
from app.repositories.medicine_repository import (  # noqa: E402
    MEDICINE_SAFETY_FACTS_VERSION,
    MedicineRepository,
)
from app.schemas.medicine import MedicineUpdateRequest  # noqa: E402
from app.schemas.records import TodayPlanCreateRequest  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.medicine_service import MedicineService  # noqa: E402
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
        self.assertNotIn("slot-03-diosmectite", safe_ids)
        self.assertNotIn("slot-13-ibuprofen", safe_ids)

    def test_reviewed_safety_facts_are_read_from_the_medicine_record(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(13)
        self.assertIsNotNone(medicine)

        updated = repository.update(
            medicine.id,
            {
                "aliases": ["芬必得", "测试审核别名"],
                "active_ingredients": ["布洛芬"],
                "structured_contraindications": [
                    {
                        "concept_code": "nsaid_allergy",
                        "display_text": "非甾体抗炎药过敏者禁用",
                    }
                ],
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 10:00:00",
            },
        )

        self.assertEqual(updated.aliases, ["芬必得", "测试审核别名"])
        self.assertEqual(updated.active_ingredients, ["布洛芬"])
        self.assertEqual(
            updated.structured_contraindications,
            [
                {
                    "concept_code": "nsaid_allergy",
                    "display_text": "非甾体抗炎药过敏者禁用",
                }
            ],
        )
        self.assertEqual(updated.safety_review_status, "reviewed")
        self.assertEqual(updated.safety_reviewed_by, "测试药师")

    def test_local_safety_content_edit_revokes_review_until_explicit_reapproval(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(13)
        repository.update(
            medicine.id,
            {
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 09:50:00",
            },
        )
        medicine = repository.get_by_id(medicine.id)
        self.assertEqual(medicine.safety_review_status, "reviewed")

        result = MedicineService(repository=repository).update_medicine(
            medicine.id,
            MedicineUpdateRequest(
                aliases=[*medicine.aliases, "新补充别名"],
                active_ingredients=[*medicine.active_ingredients, "新补充成分"],
                structured_contraindications=[
                    *medicine.structured_contraindications,
                    {
                        "concept_code": "new_review_required",
                        "display_text": "新增禁忌资料待药师核验",
                    },
                ],
            ),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.medicine.guidance_source, "manual")
        self.assertTrue(result.medicine.guidance_review_required)
        self.assertEqual(result.medicine.safety_review_status, "draft")
        self.assertEqual(result.medicine.safety_reviewed_by, "")
        self.assertEqual(result.medicine.safety_reviewed_at, "")
        self.assertNotIn(
            medicine.id,
            {
                item.id
                for item in MedicineKnowledgeRepository(repository).safe_candidate_pool("")
            },
        )

    def test_default_safety_facts_are_backfilled_as_traceable_unreviewed_drafts(self) -> None:
        medicine = MedicineRepository().get_by_hardware_slot(13)

        self.assertEqual(medicine.aliases, ["布洛芬缓释胶囊", "芬必得", "布洛芬"])
        self.assertEqual(medicine.active_ingredients, ["布洛芬"])
        self.assertIn(
            {
                "concept_code": "pregnancy",
                "display_text": "孕妇及哺乳期妇女禁用",
            },
            medicine.structured_contraindications,
        )
        self.assertEqual(medicine.safety_review_status, "draft")
        self.assertEqual(medicine.safety_reviewed_by, "")
        self.assertEqual(medicine.safety_reviewed_at, "")

    def test_v2_safety_migration_revokes_legacy_machine_review_without_overwriting_label_edits(self) -> None:
        repository = MedicineRepository()
        repository.list_all()
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET dosage='现场修改后尚未受控审核', safety_review_status='reviewed',
                    safety_reviewed_by='fixed-inventory-safety-migration',
                    safety_reviewed_at='2026-08-01 08:00:00'
                WHERE id='slot-13-ibuprofen'
                """
            )
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES ('medicine_safety_facts_version', 'database-safety-facts-v1', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (db.now_text(),),
            )

        corrected = repository.get_by_id("slot-13-ibuprofen")

        self.assertEqual(
            MEDICINE_SAFETY_FACTS_VERSION,
            "database-safety-facts-v3-controlled-ingredients",
        )
        self.assertEqual(corrected.dosage, "现场修改后尚未受控审核")
        self.assertEqual(corrected.safety_review_status, "draft")
        self.assertEqual(corrected.safety_reviewed_by, "")
        self.assertEqual(corrected.safety_reviewed_at, "")

    def test_controlled_bundled_baseline_uses_the_exact_14_item_allowlist(self) -> None:
        medicines = MedicineRepository().list_all()
        by_slot = {medicine.hardware_slot: medicine for medicine in medicines}
        bundled = [
            medicine
            for medicine in medicines
            if medicine.safety_reviewed_by == "bundled-label-reference-v2"
        ]

        self.assertEqual(
            {item.hardware_slot for item in bundled},
            {4, 6, 10, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23},
        )
        self.assertTrue(all(item.safety_review_status == "reviewed" for item in bundled))
        for slot in (1, 2, 3, 5, 7, 8, 9, 11, 13):
            self.assertEqual(by_slot[slot].safety_review_status, "draft")
            self.assertEqual(by_slot[slot].safety_reviewed_by, "")
            self.assertEqual(by_slot[slot].safety_reviewed_at, "")

    def test_v3_migration_revokes_v2_reviews_with_incomplete_ingredients(self) -> None:
        repository = MedicineRepository()
        repository.list_all()
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET safety_review_status='reviewed',
                    safety_reviewed_by='bundled-label-reference-v2',
                    safety_reviewed_at='2026-08-08 10:00:00'
                WHERE id='slot-08-huoxiang-zhengqi'
                """
            )
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES ('medicine_safety_facts_version',
                        'database-safety-facts-v2-controlled-label', ?)
                ON CONFLICT(key) DO UPDATE SET
                  value=excluded.value, updated_at=excluded.updated_at
                """,
                (db.now_text(),),
            )

        corrected = repository.get_by_id("slot-08-huoxiang-zhengqi")
        still_controlled = repository.get_by_id("slot-06-lactulose")

        self.assertEqual(corrected.safety_review_status, "draft")
        self.assertEqual(corrected.safety_reviewed_by, "")
        self.assertEqual(corrected.safety_reviewed_at, "")
        self.assertEqual(still_controlled.safety_review_status, "reviewed")
        self.assertEqual(
            still_controlled.safety_reviewed_by,
            "bundled-label-reference-v2",
        )

    def test_safety_migration_does_not_approve_modified_label_content(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(13)
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE medicines
                SET contraindications_json=?, safety_review_status='draft',
                    safety_reviewed_by='', safety_reviewed_at=''
                WHERE id=?
                """,
                (json.dumps(["管理员修改的禁忌资料待审核"], ensure_ascii=False), medicine.id),
            )
            conn.execute(
                "DELETE FROM app_settings WHERE key='medicine_safety_facts_version'"
            )

        migrated = repository.get_by_id(medicine.id)

        self.assertEqual(migrated.contraindications, ["管理员修改的禁忌资料待审核"])
        self.assertEqual(migrated.safety_review_status, "draft")
        self.assertEqual(migrated.safety_reviewed_by, "")

    def test_reviewed_combination_requires_auditable_review_metadata(self) -> None:
        repository = MedicineRepository()

        with self.assertRaisesRegex(ValueError, "审核人和审核时间"):
            repository.save_approved_combination(
                combination_id="test-combination",
                label="测试组合",
                medicine_ids=["test-a", "test-b"],
                review_status="reviewed",
                reviewed_by="",
                reviewed_at="",
            )

    def test_reviewed_drug_combination_rejects_members_without_active_ingredients(self) -> None:
        repository = MedicineRepository()
        unknown_ingredients = repository.get_by_hardware_slot(8)
        known_ingredients = repository.get_by_hardware_slot(6)
        repository.update(
            unknown_ingredients.id,
            {
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 12:05:00",
            },
        )

        with self.assertRaisesRegex(ValueError, "有效成分"):
            repository.save_approved_combination(
                combination_id="unknown-ingredient-pair",
                label="未知成分组合",
                medicine_ids=[unknown_ingredients.id, known_ingredients.id],
                review_status="reviewed",
                reviewed_by="测试药师",
                reviewed_at="2026-08-08 12:10:00",
            )

    def test_non_drug_exception_is_bound_to_the_current_product_identity(self) -> None:
        repository = MedicineRepository()
        supply = repository.get_by_hardware_slot(10)
        known_drug = repository.get_by_hardware_slot(6)
        repository.save_approved_combination(
            combination_id="supply-baseline-pair",
            label="受控护理用品组合",
            medicine_ids=[supply.id, known_drug.id],
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 12:12:00",
        )

        repository.update(
            supply.id,
            {
                "name": "同仓位空成分药品",
                "category": "家庭常用",
                "spec": "新药规格",
            },
        )
        repository.update(
            supply.id,
            {
                "aliases": ["同仓位空成分药品"],
                "active_ingredients": [],
                "indications": "用于测试症状",
                "dosage": "按说明书使用",
                "contraindications": ["对本品过敏者禁用"],
                "structured_contraindications": [
                    {
                        "concept_code": "ingredient_allergy",
                        "display_text": "对本品过敏者禁用",
                    }
                ],
                "is_otc": True,
                "guidance_source": "verified_label",
                "guidance_review_required": False,
                "package_verified": True,
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 12:14:00",
            },
        )

        with self.assertRaisesRegex(ValueError, "有效成分"):
            repository.save_approved_combination(
                combination_id="reused-row-pair",
                label="换药后组合",
                medicine_ids=[supply.id, known_drug.id],
                review_status="reviewed",
                reviewed_by="测试药师",
                reviewed_at="2026-08-08 12:15:00",
            )

    def test_combination_larger_than_four_is_rejected_instead_of_truncated(self) -> None:
        repository = MedicineRepository()

        with self.assertRaisesRegex(ValueError, "2 至 4"):
            repository.save_approved_combination(
                combination_id="too-large",
                label="过大组合",
                medicine_ids=["test-a", "test-b", "test-c", "test-d", "test-e"],
            )

        with db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM approved_medicine_combinations"
            ).fetchone()["count"]
        self.assertEqual(count, 0)

    def test_only_auditable_reviewed_combinations_are_available(self) -> None:
        repository = MedicineRepository()
        reviewed_ids = [
            repository.get_by_hardware_slot(4).id,
            repository.get_by_hardware_slot(6).id,
        ]
        repository.save_approved_combination(
            combination_id="reviewed-pair",
            label="药师审核组合",
            medicine_ids=reviewed_ids,
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 12:00:00",
        )
        repository.save_approved_combination(
            combination_id="draft-pair",
            label="待审核组合",
            medicine_ids=["test-a", "test-c"],
        )

        combinations = repository.list_reviewed_combinations()

        self.assertEqual([item.combination_id for item in combinations], ["reviewed-pair"])
        self.assertEqual(combinations[0].medicine_ids, reviewed_ids)
        self.assertEqual(set(combinations[0].member_identity_fingerprints), set(reviewed_ids))
        self.assertEqual(combinations[0].reviewed_by, "测试药师")

    def test_combination_member_snapshot_and_insert_share_one_write_transaction(self) -> None:
        repository = MedicineRepository()
        reviewed_ids = [
            repository.get_by_hardware_slot(4).id,
            repository.get_by_hardware_slot(6).id,
        ]
        real_connect = db.connect
        connection_calls: list[object] = []

        def tracked_connect(*args, **kwargs):
            connection_calls.append(object())
            return real_connect(*args, **kwargs)

        with patch.object(repository, "_ensure_seeded", return_value=None), patch(
            "app.repositories.medicine_repository.db.connect",
            side_effect=tracked_connect,
        ):
            repository.save_approved_combination(
                combination_id="single-transaction-pair",
                label="同事务组合",
                medicine_ids=reviewed_ids,
                review_status="reviewed",
                reviewed_by="测试药师",
                reviewed_at="2026-08-08 12:02:00",
            )

        self.assertEqual(len(connection_calls), 1)

    def test_reviewed_ingredient_conflict_requires_metadata_and_is_order_independent(self) -> None:
        repository = MedicineRepository()

        with self.assertRaisesRegex(ValueError, "只允许 block"):
            repository.save_ingredient_conflict(
                left_ingredient="布洛芬",
                right_ingredient="对乙酰氨基酚",
                disposition="blocked",
            )

        with self.assertRaisesRegex(ValueError, "审核人和审核时间"):
            repository.save_ingredient_conflict(
                left_ingredient="布洛芬",
                right_ingredient="对乙酰氨基酚",
                review_status="reviewed",
            )

        repository.save_ingredient_conflict(
            left_ingredient=" 对乙酰氨基酚 ",
            right_ingredient="布洛芬",
            message="药师标记为不可同用",
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 12:30:00",
        )

        rules = repository.list_reviewed_ingredient_conflicts()
        self.assertEqual(len(rules), 1)
        self.assertEqual(
            {rules[0].left_ingredient, rules[0].right_ingredient},
            {"布洛芬", "对乙酰氨基酚"},
        )
        self.assertEqual(rules[0].message, "药师标记为不可同用")

    def test_reviewed_combination_is_bound_to_each_members_identity_fingerprint(self) -> None:
        repository = MedicineRepository()
        first = repository.get_by_hardware_slot(3)
        second = repository.get_by_hardware_slot(6)
        repository.update(
            first.id,
            {
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 13:25:00",
            },
        )
        first = repository.get_by_id(first.id)
        repository.save_approved_combination(
            combination_id="identity-bound-pair",
            label="身份绑定测试组合",
            medicine_ids=[first.id, second.id],
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 13:30:00",
        )
        knowledge = MedicineKnowledgeRepository(repository)
        initial_pool = knowledge.safe_candidate_pool("")
        initial = knowledge.validate_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id]}]},
            initial_pool,
        )
        self.assertEqual(len(initial.options), 1)

        repository.update(first.id, {"spec": "身份已更换的新规格"})
        with db.connect() as conn:
            invalidated = conn.execute(
                "SELECT review_status FROM approved_medicine_combinations WHERE combination_id=?",
                ("identity-bound-pair",),
            ).fetchone()
        self.assertEqual(invalidated["review_status"], "invalidated")
        repository.update(
            first.id,
            {
                "aliases": [first.name],
                "active_ingredients": first.active_ingredients,
                "indications": first.indications,
                "dosage": first.dosage,
                "contraindications": first.contraindications,
                "structured_contraindications": first.structured_contraindications,
                "is_otc": first.is_otc,
                "is_emergency": first.is_emergency,
                "guidance_source": "verified_label",
                "guidance_review_required": False,
                "package_verified": True,
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 13:35:00",
            },
        )
        fresh_pool = knowledge.safe_candidate_pool("")
        self.assertTrue({first.id, second.id}.issubset({item.id for item in fresh_pool}))

        after_identity_change = knowledge.validate_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id]}]},
            fresh_pool,
        )

        self.assertEqual(after_identity_change.options, [])
        self.assertEqual(
            [notice.code for notice in after_identity_change.notices],
            ["combination_not_approved"],
        )

    def test_identity_change_invalidates_linked_today_plans_in_the_same_transaction(self) -> None:
        repository = MedicineRepository()
        medicine = repository.get_by_hardware_slot(13)
        plan = RecordsService().create_today_plan(
            TodayPlanCreateRequest(
                time="09:15",
                medicine_id=medicine.id,
                service_user_id="zhangsan",
            )
        )

        repository.update(medicine.id, {"spec": "计划不应沿用的新规格"})

        with db.connect() as conn:
            stored_plan = conn.execute(
                "SELECT id FROM today_plans WHERE id=?",
                (plan.id,),
            ).fetchone()
            stored_medicine = conn.execute(
                "SELECT spec FROM medicines WHERE id=?",
                (medicine.id,),
            ).fetchone()
        self.assertIsNone(stored_plan)
        self.assertEqual(stored_medicine["spec"], "计划不应沿用的新规格")

    def test_safety_content_change_permanently_invalidates_reviewed_combinations(self) -> None:
        repository = MedicineRepository()
        first = repository.get_by_hardware_slot(3)
        second = repository.get_by_hardware_slot(6)
        repository.update(
            first.id,
            {
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 14:05:00",
            },
        )
        first = repository.get_by_id(first.id)
        repository.save_approved_combination(
            combination_id="safety-bound-pair",
            label="安全资料绑定测试组合",
            medicine_ids=[first.id, second.id],
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 14:10:00",
        )

        repository.update(first.id, {"aliases": [*first.aliases, "新草稿别名"]})
        repository.update(
            first.id,
            {
                "aliases": first.aliases,
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 14:15:00",
            },
        )

        self.assertEqual(repository.list_reviewed_combinations(), [])
        with db.connect() as conn:
            stored = conn.execute(
                "SELECT review_status, reviewed_by, reviewed_at "
                "FROM approved_medicine_combinations WHERE combination_id=?",
                ("safety-bound-pair",),
            ).fetchone()
        self.assertEqual(stored["review_status"], "invalidated")
        self.assertEqual(stored["reviewed_by"], "")
        self.assertEqual(stored["reviewed_at"], "")

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
