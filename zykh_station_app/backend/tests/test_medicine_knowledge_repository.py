from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import CandidateMedicine  # noqa: E402
from app.schemas.medicine import (  # noqa: E402
    ApprovedMedicineCombination,
    Medicine,
    MedicineIngredientConflictRule,
)
from app.services.medicine_knowledge_repository import (  # noqa: E402
    MedicineKnowledgeRepository,
    MedicineSafetyContext,
)


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
    aliases: list[str] | None = None,
    active_ingredients: list[str] | None = None,
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
        aliases=aliases or [],
        active_ingredients=active_ingredients or [],
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
        safety_review_status="reviewed",
        safety_reviewed_by="测试药师",
        safety_reviewed_at="2026-08-08 10:00:00",
    )


class SequenceMedicineRepository:
    def __init__(self, snapshots: list[list[Medicine]]) -> None:
        self.snapshots = list(snapshots)
        self.calls = 0

    def list_all(self) -> list[Medicine]:
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


class SafetyPolicyRepository:
    def __init__(self, *, combinations=None, conflicts=None, fingerprints=None) -> None:
        self.combinations = list(combinations or [])
        self.conflicts = list(conflicts or [])
        self.fingerprints = dict(fingerprints or {})

    def list_reviewed_combinations(self):
        return list(self.combinations)

    def list_reviewed_ingredient_conflicts(self):
        return list(self.conflicts)

    def get_identity_fingerprints(self, medicine_ids: list[str]) -> dict[str, str]:
        return {
            medicine_id: self.fingerprints[medicine_id]
            for medicine_id in medicine_ids
            if medicine_id in self.fingerprints
        }


class MedicineKnowledgeRepositoryTest(unittest.TestCase):
    def test_current_episode_brand_or_ingredient_blocks_the_same_medicine(self) -> None:
        ibuprofen = cabinet_medicine(
            "slot-13-ibuprofen",
            "布洛芬缓释胶囊",
            tags=["芬必得", "退热"],
            contraindications=["非甾体抗炎药过敏者禁用"],
            aliases=["芬必得", "布洛芬"],
            active_ingredients=["布洛芬"],
        )
        cold_medicine = cabinet_medicine(
            "slot-01-fufang-ganmaoling",
            "复方感冒灵颗粒",
            contraindications=["避免与同类解热镇痛药重复使用"],
            active_ingredients=["对乙酰氨基酚"],
        )

        for used, medicine in (
            ("芬必得", ibuprofen),
            ("布洛芬", ibuprofen),
            ("对乙酰氨基酚", cold_medicine),
        ):
            with self.subTest(used=used):
                repository = MedicineKnowledgeRepository(SequenceMedicineRepository([[medicine]]))
                self.assertEqual(repository.safe_candidate_pool(f"已用药：{used}"), [])

    def test_runtime_conflict_matching_uses_entity_facts_for_a_dynamic_id(self) -> None:
        medicine = cabinet_medicine(
            "scan-dynamic-product",
            "动态录入药品",
        ).model_copy(
            update={
                "aliases": ["动态品牌名"],
                "active_ingredients": ["动态审核成分"],
                "safety_review_status": "reviewed",
                "safety_reviewed_by": "测试药师",
                "safety_reviewed_at": "2026-08-08 10:00:00",
            }
        )
        repository = MedicineKnowledgeRepository(SequenceMedicineRepository([[medicine]]))

        self.assertEqual(repository.safe_candidate_pool("已用药：动态审核成分"), [])

    def test_brand_allergy_and_chronic_contraindication_are_hard_filters(self) -> None:
        ibuprofen = cabinet_medicine(
            "slot-13-ibuprofen",
            "布洛芬缓释胶囊",
            tags=["芬必得"],
            contraindications=["非甾体抗炎药过敏者禁用"],
            aliases=["芬必得", "布洛芬"],
            active_ingredients=["布洛芬"],
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

    def test_dynamic_structured_contraindication_participates_in_allergy_matching(self) -> None:
        medicine = cabinet_medicine(
            "scan-structured-allergy",
            "动态审核药品",
            contraindications=[],
        ).model_copy(
            update={
                "contraindications": [],
                "structured_contraindications": [
                    {
                        "concept_code": "ingredient_allergy",
                        "display_text": "测试辅料过敏者禁用",
                    }
                ]
            }
        )

        self.assertTrue(
            MedicineKnowledgeRepository.has_allergy_conflict(
                medicine,
                "过敏/禁忌：测试辅料过敏",
            )
        )

    def test_dynamic_structured_concept_participates_in_history_matching(self) -> None:
        medicine = cabinet_medicine(
            "scan-structured-history",
            "动态审核药品",
        ).model_copy(
            update={
                "contraindications": [],
                "structured_contraindications": [
                    {
                        "concept_code": "diabetes",
                        "display_text": "相关人群禁用",
                    }
                ],
            }
        )

        self.assertTrue(
            MedicineKnowledgeRepository.has_chronic_condition_conflict(
                medicine,
                "既往资料：患有糖尿病",
            )
        )

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

    def test_selection_larger_than_four_is_rejected_as_a_whole_with_notice(self) -> None:
        repository = MedicineKnowledgeRepository()
        pool = [
            candidate(
                f"medicine-{index}",
                f"测试药品{index}",
                "家庭常用",
                [f"症状{index}"],
                f"用于症状{index}",
                active_ingredients=[f"成分{index}"],
            )
            for index in range(5)
        ]

        assessment = repository.validate_ai_selection(
            {"options": [{"medicine_ids": [item.id for item in pool]}]},
            pool,
        )

        self.assertEqual(assessment.options, [])
        self.assertEqual([notice.code for notice in assessment.notices], ["combination_too_large"])

    def test_multi_medicine_selection_requires_an_exact_reviewed_combination(self) -> None:
        first = candidate(
            "cold-care",
            "感冒护理药",
            "感冒发热",
            ["鼻塞"],
            "用于感冒鼻塞",
            active_ingredients=["成分甲"],
        )
        second = candidate(
            "throat-care",
            "咽喉护理药",
            "咽喉口腔",
            ["咽痛"],
            "用于咽喉疼痛",
            active_ingredients=["成分乙"],
        )
        repository = MedicineKnowledgeRepository(SafetyPolicyRepository())

        assessment = repository.validate_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id]}]},
            [first, second],
        )

        self.assertEqual(assessment.options, [])
        self.assertEqual(
            [notice.code for notice in assessment.notices],
            ["combination_not_approved"],
        )

    def test_same_ingredient_blocks_even_an_approved_combination_first(self) -> None:
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
        approved = ApprovedMedicineCombination(
            combination_id="approved-but-conflicted",
            label="测试组合",
            medicine_ids=[first.id, second.id],
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 13:00:00",
        )
        repository = MedicineKnowledgeRepository(
            SafetyPolicyRepository(combinations=[approved])
        )

        assessment = repository.validate_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id]}]},
            [first, second],
        )

        self.assertEqual(assessment.options, [])
        self.assertEqual([notice.code for notice in assessment.notices], ["ingredient_conflict"])
        self.assertIn("对乙酰氨基酚", assessment.notices[0].message)

    def test_reviewed_conflict_matrix_blocks_an_approved_combination(self) -> None:
        first = candidate(
            "medicine-a",
            "药品甲",
            "家庭常用",
            ["症状甲"],
            "用于症状甲",
            active_ingredients=["成分甲"],
        )
        second = candidate(
            "medicine-b",
            "药品乙",
            "家庭常用",
            ["症状乙"],
            "用于症状乙",
            active_ingredients=["成分乙"],
        )
        approved = ApprovedMedicineCombination(
            combination_id="approved-pair",
            label="测试组合",
            medicine_ids=[first.id, second.id],
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 13:00:00",
        )
        blocked = MedicineIngredientConflictRule(
            left_ingredient="成分乙",
            right_ingredient="成分甲",
            message="药师审核为不可同用",
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 13:05:00",
        )
        repository = MedicineKnowledgeRepository(
            SafetyPolicyRepository(combinations=[approved], conflicts=[blocked])
        )

        assessment = repository.validate_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id]}]},
            [first, second],
        )

        self.assertEqual(assessment.options, [])
        self.assertEqual([notice.code for notice in assessment.notices], ["ingredient_conflict"])
        self.assertIn("药师审核为不可同用", assessment.notices[0].message)

    def test_legacy_identity_only_combination_is_rejected_without_case_authorization(self) -> None:
        first = candidate(
            "medicine-a",
            "药品甲",
            "家庭常用",
            ["症状甲"],
            "用于症状甲",
            active_ingredients=["成分甲"],
        )
        second = candidate(
            "medicine-b",
            "药品乙",
            "家庭常用",
            ["症状乙"],
            "用于症状乙",
            active_ingredients=["成分乙"],
        )
        fingerprints = {first.id: "fingerprint-a", second.id: "fingerprint-b"}
        approved = ApprovedMedicineCombination(
            combination_id="identity-bound-pair",
            label="测试组合",
            medicine_ids=[first.id, second.id],
            member_identity_fingerprints=fingerprints,
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 13:10:00",
        )
        repository = MedicineKnowledgeRepository(
            SafetyPolicyRepository(
                combinations=[approved],
                fingerprints=fingerprints,
            )
        )

        assessment = repository.validate_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id]}]},
            [first, second],
        )

        self.assertEqual(assessment.options, [])
        self.assertEqual(assessment.notices[0].code, "combination_not_approved")

    def test_approved_combination_still_rejects_a_drug_with_unknown_ingredients(self) -> None:
        unknown = candidate(
            "unknown-ingredient-drug",
            "未知成分药品",
            "家庭常用",
            ["症状甲"],
            "用于症状甲",
            active_ingredients=[],
        )
        known = candidate(
            "known-ingredient-drug",
            "已知成分药品",
            "家庭常用",
            ["症状乙"],
            "用于症状乙",
            active_ingredients=["成分乙"],
        )
        fingerprints = {unknown.id: "fingerprint-a", known.id: "fingerprint-b"}
        approved = ApprovedMedicineCombination(
            combination_id="legacy-approved-unknown-ingredients",
            label="旧审批组合",
            medicine_ids=[unknown.id, known.id],
            member_identity_fingerprints=fingerprints,
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 13:20:00",
        )
        repository = MedicineKnowledgeRepository(
            SafetyPolicyRepository(
                combinations=[approved],
                fingerprints=fingerprints,
            )
        )

        assessment = repository.validate_ai_selection(
            {"options": [{"medicine_ids": [unknown.id, known.id]}]},
            [unknown, known],
        )

        self.assertEqual(assessment.options, [])
        self.assertEqual(
            [notice.code for notice in assessment.notices],
            ["combination_not_approved"],
        )

    def test_known_ingredient_conflict_notice_precedes_unknown_ingredient_rejection(self) -> None:
        first = candidate(
            "duplicate-a",
            "重复成分药品甲",
            "家庭常用",
            ["症状甲"],
            "用于症状甲",
            active_ingredients=["重复成分"],
        )
        second = candidate(
            "duplicate-b",
            "重复成分药品乙",
            "家庭常用",
            ["症状乙"],
            "用于症状乙",
            active_ingredients=["重复成分"],
        )
        unknown = candidate(
            "unknown-c",
            "未知成分药品丙",
            "家庭常用",
            ["症状丙"],
            "用于症状丙",
            active_ingredients=[],
        )
        repository = MedicineKnowledgeRepository(SafetyPolicyRepository())

        assessment = repository.validate_ai_selection(
            {"options": [{"medicine_ids": [first.id, second.id, unknown.id]}]},
            [first, second, unknown],
        )

        self.assertEqual(assessment.options, [])
        self.assertEqual([notice.code for notice in assessment.notices], ["ingredient_conflict"])

    def test_each_candidate_pool_read_uses_the_latest_inventory_snapshot(self) -> None:
        available = cabinet_medicine("slot-13-ibuprofen", "布洛芬缓释胶囊", stock=1)
        depleted = available.model_copy(update={"stock": 0})
        source = SequenceMedicineRepository([[available], [depleted]])
        repository = MedicineKnowledgeRepository(source)

        self.assertEqual([item.id for item in repository.safe_candidate_pool("")], [available.id])
        self.assertEqual(repository.safe_candidate_pool(""), [])
        self.assertEqual(source.calls, 2)

    def test_unreviewed_safety_profile_is_not_a_candidate(self) -> None:
        pending = cabinet_medicine(
            "scan-pending-safety",
            "安全资料待审核药品",
        ).model_copy(
            update={
                "safety_review_status": "draft",
                "safety_reviewed_by": "",
                "safety_reviewed_at": "",
            }
        )
        repository = MedicineKnowledgeRepository(SequenceMedicineRepository([[pending]]))

        self.assertEqual(repository.safe_candidate_pool(""), [])

    def test_assessment_reports_a_relevant_used_ingredient_conflict(self) -> None:
        cold_medicine = cabinet_medicine(
            "dynamic-cold",
            "复方感冒灵颗粒",
            tags=["发热", "咽痛"],
            active_ingredients=["对乙酰氨基酚"],
        )
        throat_medicine = cabinet_medicine(
            "dynamic-throat",
            "咽喉护理药",
            tags=["咽痛"],
        )
        repository = MedicineKnowledgeRepository(
            SequenceMedicineRepository([[cold_medicine, throat_medicine]])
        )

        assessment = repository.assess_candidates(
            MedicineSafetyContext(
                context_text="已用药：对乙酰氨基酚；过敏/禁忌：无",
                relevance_text="咽喉疼痛并有轻微发热",
            )
        )

        self.assertEqual([item.id for item in assessment.candidates], ["dynamic-throat"])
        self.assertEqual([item.code for item in assessment.notices], ["used_medicine_duplicate"])
        self.assertIn("复方感冒灵颗粒", assessment.notices[0].message)
        self.assertIn("对乙酰氨基酚", assessment.notices[0].message)
        self.assertIn("重复", assessment.notices[0].message)

    def test_conflicted_relevant_item_does_not_consume_the_safe_result_limit(self) -> None:
        conflicted = cabinet_medicine(
            "conflicted-first",
            "先排序的冲突药品",
            tags=["咽痛"],
            active_ingredients=["已用成分"],
        )
        safe = cabinet_medicine(
            "safe-second",
            "后排序的安全药品",
            tags=["咽痛"],
        )
        repository = MedicineKnowledgeRepository(
            SequenceMedicineRepository([[conflicted, safe]])
        )

        assessment = repository.assess_candidates(
            MedicineSafetyContext(
                context_text="已用药：已用成分；过敏/禁忌：无",
                relevance_text="咽痛",
            ),
            limit=1,
        )

        self.assertEqual([item.id for item in assessment.candidates], ["safe-second"])
        self.assertEqual([item.code for item in assessment.notices], ["used_medicine_duplicate"])

    def test_history_and_allergy_sources_produce_the_matching_notice_code(self) -> None:
        contraindicated = cabinet_medicine(
            "history-sensitive",
            "病史敏感药品",
            tags=["咳嗽"],
        ).model_copy(
            update={
                "contraindications": ["糖尿病患者禁用"],
                "structured_contraindications": [
                    {
                        "concept_code": "diabetes",
                        "display_text": "糖尿病患者禁用",
                    }
                ],
            }
        )
        repository = MedicineKnowledgeRepository(
            SequenceMedicineRepository([[contraindicated]])
        )

        assessment = repository.assess_candidates(
            MedicineSafetyContext(
                context_text="糖尿病；无药物过敏",
                history_text="糖尿病",
                allergy_text="无药物过敏",
                relevance_text="咳嗽",
            )
        )

        self.assertEqual(assessment.candidates, [])
        self.assertEqual(
            [notice.code for notice in assessment.notices],
            ["history_contraindication"],
        )

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
