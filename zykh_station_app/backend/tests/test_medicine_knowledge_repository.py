from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import CandidateMedicine  # noqa: E402
from app.schemas.medicine import Medicine  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402


def candidate(
    medicine_id: str,
    name: str,
    category: str,
    tags: list[str],
    indications: str,
    contraindications: list[str] | None = None,
    active_ingredients: list[str] | None = None,
) -> CandidateMedicine:
    return CandidateMedicine(
        id=medicine_id,
        name=name,
        category=category,
        slot="1",
        stock=2,
        unit="盒",
        safety_note="核对说明书",
        indications=indications,
        dosage="按说明书使用",
        tags=tags,
        contraindications=contraindications or ["对本品过敏禁用"],
        active_ingredients=active_ingredients or [],
    )


def cabinet_medicine(
    medicine_id: str,
    name: str,
    *,
    tags: list[str] | None = None,
    contraindications: list[str] | None = None,
    stock: int = 1,
) -> Medicine:
    return Medicine(
        id=medicine_id,
        slot="S13",
        hardware_slot=13,
        barcode="test-barcode",
        manufacturer="测试厂家",
        name=name,
        category="解热镇痛",
        tags=tags or [],
        indications="用于经核验的对应症状",
        dosage="按说明书使用",
        contraindications=contraindications or ["对本品过敏禁用"],
        stock=stock,
        unit="盒",
        expire_date="2030-12",
        image_hint=name,
        is_otc=True,
        is_emergency=False,
        safety_note="核对说明书",
        guidance_source="verified_label",
        guidance_review_required=False,
        package_verified=True,
    )


class SequenceMedicineRepository:
    def __init__(self, snapshots: list[list[Medicine]]) -> None:
        self.snapshots = list(snapshots)
        self.calls = 0

    def list_all(self) -> list[Medicine]:
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


class MedicineKnowledgeRepositoryTest(unittest.TestCase):
    def test_current_episode_brand_or_ingredient_blocks_the_same_medicine(self) -> None:
        ibuprofen = cabinet_medicine(
            "slot-13-ibuprofen",
            "布洛芬缓释胶囊",
            tags=["芬必得", "退热"],
            contraindications=["非甾体抗炎药过敏者禁用"],
        )
        cold_medicine = cabinet_medicine(
            "slot-01-fufang-ganmaoling",
            "复方感冒灵颗粒",
            contraindications=["避免与同类解热镇痛药重复使用"],
        )

        for used, medicine in (
            ("芬必得", ibuprofen),
            ("布洛芬", ibuprofen),
            ("对乙酰氨基酚", cold_medicine),
        ):
            with self.subTest(used=used):
                repository = MedicineKnowledgeRepository(SequenceMedicineRepository([[medicine]]))
                self.assertEqual(repository.safe_candidate_pool(f"已用药：{used}"), [])

    def test_brand_allergy_and_chronic_contraindication_are_hard_filters(self) -> None:
        ibuprofen = cabinet_medicine(
            "slot-13-ibuprofen",
            "布洛芬缓释胶囊",
            tags=["芬必得"],
            contraindications=["非甾体抗炎药过敏者禁用"],
        )
        cough_syrup = cabinet_medicine(
            "slot-05-nin-jiom-pei-pa-koa",
            "蜜炼川贝枇杷膏",
            contraindications=["糖尿病患者禁用"],
        )

        allergy_repository = MedicineKnowledgeRepository(SequenceMedicineRepository([[ibuprofen]]))
        chronic_repository = MedicineKnowledgeRepository(SequenceMedicineRepository([[cough_syrup]]))

        self.assertEqual(allergy_repository.safe_candidate_pool("过敏/禁忌：芬必得"), [])
        self.assertEqual(chronic_repository.safe_candidate_pool("既往资料：患有糖尿病"), [])

    def test_negated_chronic_condition_does_not_create_a_false_conflict(self) -> None:
        cough_syrup = cabinet_medicine(
            "slot-05-nin-jiom-pei-pa-koa",
            "蜜炼川贝枇杷膏",
            contraindications=["糖尿病患者禁用"],
        )
        repository = MedicineKnowledgeRepository(SequenceMedicineRepository([[cough_syrup]]))

        self.assertEqual(
            [item.id for item in repository.safe_candidate_pool("既往资料：没有糖尿病")],
            ["slot-05-nin-jiom-pei-pa-koa"],
        )

    def test_duplicate_active_ingredient_rejects_a_model_combination(self) -> None:
        repository = MedicineKnowledgeRepository()
        first = candidate(
            "compound-cold",
            "复方感冒药",
            "感冒发热",
            ["发热"],
            "用于感冒发热",
            active_ingredients=["对乙酰氨基酚"],
        )
        second = candidate(
            "acetaminophen",
            "对乙酰氨基酚片",
            "解热镇痛",
            ["发热"],
            "用于退热",
            active_ingredients=["对乙酰氨基酚"],
        )

        options = repository.options_from_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id]}]},
            [first, second],
        )

        self.assertEqual(options, [])

    def test_each_candidate_pool_read_uses_the_latest_inventory_snapshot(self) -> None:
        available = cabinet_medicine("slot-13-ibuprofen", "布洛芬缓释胶囊", stock=1)
        depleted = available.model_copy(update={"stock": 0})
        source = SequenceMedicineRepository([[available], [depleted]])
        repository = MedicineKnowledgeRepository(source)

        self.assertEqual([item.id for item in repository.safe_candidate_pool("")], [available.id])
        self.assertEqual(repository.safe_candidate_pool(""), [])
        self.assertEqual(source.calls, 2)

    def test_retrieval_narrows_prompt_without_dropping_direct_symptom_matches(self) -> None:
        pool = [
            candidate("throat", "咽喉护理药", "咽喉口腔", ["咽痛"], "用于咽喉肿痛"),
            candidate("headache", "头痛护理药", "解热镇痛", ["头痛"], "用于轻度头痛"),
            *[
                candidate(f"other-{index}", f"其他药{index}", "其他", [f"用途{index}"], f"其他用途{index}")
                for index in range(10)
            ],
        ]

        focused = MedicineKnowledgeRepository.focus_candidate_pool(
            "今天早上开始咽喉疼痛并伴有头痛",
            pool,
            limit=6,
        )

        ids = {item.id for item in focused}
        self.assertLessEqual(len(focused), 6)
        self.assertIn("throat", ids)
        self.assertIn("headache", ids)

    def test_retrieval_returns_empty_when_no_symptom_reliably_matches(self) -> None:
        pool = [
            candidate("throat", "咽喉护理药", "咽喉口腔", ["咽痛"], "用于咽喉肿痛"),
            candidate("headache", "头痛护理药", "解热镇痛", ["头痛"], "用于轻度头痛"),
        ]

        focused = MedicineKnowledgeRepository.focus_candidate_pool(
            "昨晚开始乏力",
            pool,
            limit=8,
        )

        self.assertEqual(focused, [])

    def test_retrieval_returns_only_reliable_matches_within_the_limit(self) -> None:
        pool = [
            candidate("throat", "咽喉护理药", "咽喉口腔", ["咽痛"], "用于咽喉肿痛"),
            candidate("headache", "头痛护理药", "解热镇痛", ["头痛"], "用于轻度头痛"),
            candidate("stomach", "胃部护理药", "消化系统", ["胃痛"], "用于胃部不适"),
        ]

        focused = MedicineKnowledgeRepository.focus_candidate_pool(
            "今天吞咽时咽痛",
            pool,
            limit=2,
        )

        self.assertLessEqual(len(focused), 2)
        self.assertEqual([item.id for item in focused], ["throat"])

    def test_explicit_same_class_duplicate_warning_rejects_a_combination(self) -> None:
        repository = MedicineKnowledgeRepository()
        first = candidate(
            "cold-a",
            "感冒药A",
            "感冒发热",
            ["发热"],
            "用于感冒发热",
            ["避免与同类药物重复使用"],
        )
        second = candidate(
            "cold-b",
            "感冒药B",
            "感冒发热",
            ["鼻塞"],
            "用于感冒鼻塞",
        )

        options = repository.options_from_ai_selection(
            {
                "options": [
                    {
                        "medicine_ids": ["cold-a", "cold-b"],
                        "reason": "组合使用",
                    }
                ]
            },
            [first, second],
        )

        self.assertEqual(options, [])

    def test_personalized_reason_is_kept_separate_from_usage(self) -> None:
        repository = MedicineKnowledgeRepository()
        medicine = candidate(
            "throat",
            "咽喉护理药",
            "咽喉口腔",
            ["咽痛"],
            "用于咽喉肿痛",
        )
        options = repository.options_from_ai_selection(
            {
                "options": [
                    {
                        "medicine_ids": ["throat"],
                        "reason": "当前主要是吞咽时咽痛。",
                        "reason_by_medicine": {"throat": "针对你吞咽时加重的咽喉疼痛。"},
                        "usage_by_medicine": {"throat": "按说明书含服"},
                    }
                ]
            },
            [medicine],
        )
        selected = options[0].medicines[0]
        self.assertEqual(selected.match_reason, "针对你吞咽时加重的咽喉疼痛。")
        self.assertEqual(selected.recommended_usage, "按说明书含服")


if __name__ == "__main__":
    unittest.main()
