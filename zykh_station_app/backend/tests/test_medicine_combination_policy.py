from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import CandidateMedicine  # noqa: E402
from app import db  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.schemas.medicine import (  # noqa: E402
    ApprovedMedicineCombination,
    MedicineCombinationApplicability,
    MedicineCombinationEvidenceRef,
)
from app.services.medicine_combination_policy import (  # noqa: E402
    CombinationClinicalContext,
    MedicineCombinationPolicy,
    combination_context_from_observations,
)
from app.services.medicine_knowledge_repository import (  # noqa: E402
    MedicineKnowledgeRepository,
)


def candidate(medicine_id: str, fingerprint: str) -> CandidateMedicine:
    return CandidateMedicine(
        id=medicine_id,
        name=medicine_id,
        category="测试",
        slot="1",
        stock=1,
        unit="盒",
        safety_note="核对说明书",
        active_ingredients=[medicine_id],
        review_fingerprint=fingerprint,
    )


def reviewed_diarrhea_combination() -> ApprovedMedicineCombination:
    medicine_ids = ["slot-03-diosmectite", "slot-09-bifid-triple"]
    return ApprovedMedicineCombination(
        combination_id="adult-watery-diarrhea-separated",
        label="成人水样腹泻分时用药",
        medicine_ids=medicine_ids,
        member_identity_fingerprints={item: f"identity-{item}" for item in medicine_ids},
        clinical_policy_version="case-applicability-v1",
        applicability=MedicineCombinationApplicability(
            required_all_facts=["acute_watery_diarrhea"],
            must_be_absent_facts=[
                "bloody_stool",
                "black_stool",
                "persistent_high_fever",
                "severe_abdominal_pain",
                "significant_dehydration",
                "persistent_vomiting",
            ],
            member_required_any_facts={
                medicine_id: ["acute_watery_diarrhea"] for medicine_id in medicine_ids
            },
            allowed_risk_levels=["low"],
            min_age_years=18,
        ),
        member_review_fingerprints={
            "slot-03-diosmectite": "review-03",
            "slot-09-bifid-triple": "review-09",
        },
        reviewed_usage_by_medicine={
            "slot-03-diosmectite": "先按说明书服用蒙脱石散。",
            "slot-09-bifid-triple": "与蒙脱石散间隔至少 2 小时后按说明书服用。",
        },
        evidence_refs=[
            MedicineCombinationEvidenceRef(
                source_title="湖北省卫生健康委员会腹泻用药科普",
                source_url=(
                    "https://wjw.hubei.gov.cn/bmdt/mtjj/mtgz/"
                    "202301/t20230109_4481080.shtml"
                ),
                supports="蒙脱石散与其他药物应间隔至少 1 至 2 小时。",
            )
        ],
        provenance="official-evidence-candidate-v1",
        review_note="药师确认成人适用条件和分时用法。",
        review_status="reviewed",
        reviewed_by="测试药师",
        reviewed_at="2026-08-08 16:00:00",
        updated_at="2026-08-08 16:00:00",
    )


class FakeCombinationRepository:
    def __init__(self, combinations: list[ApprovedMedicineCombination]) -> None:
        self.combinations = combinations

    def list_case_reviewed_combinations(self) -> list[ApprovedMedicineCombination]:
        return list(self.combinations)

    def list_reviewed_ingredient_conflicts(self) -> list[object]:
        return []


class MedicineCombinationPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.combination = reviewed_diarrhea_combination()
        self.safe_pool = [
            candidate("slot-03-diosmectite", "review-03"),
            candidate("slot-09-bifid-triple", "review-09"),
        ]
        self.context = CombinationClinicalContext(
            present_facts=frozenset({"acute_watery_diarrhea"}),
            absent_facts=frozenset(self.combination.applicability.must_be_absent_facts),
            risk_level="low",
            age_years=35,
        )

    def test_one_authorization_drives_model_catalog_and_backend_expansion(self) -> None:
        authorization = MedicineCombinationPolicy(
            FakeCombinationRepository([self.combination])
        ).authorize(self.context, self.safe_pool)

        self.assertEqual(
            [item.combination_id for item in authorization.allowed_combinations],
            ["adult-watery-diarrhea-separated"],
        )
        self.assertEqual(
            authorization.model_payload(),
            [
                {
                    "combination_id": "adult-watery-diarrhea-separated",
                    "label": "成人水样腹泻分时用药",
                    "medicine_ids": ["slot-03-diosmectite", "slot-09-bifid-triple"],
                    "reviewed_usage_by_medicine": {
                        "slot-03-diosmectite": "先按说明书服用蒙脱石散。",
                        "slot-09-bifid-triple": "与蒙脱石散间隔至少 2 小时后按说明书服用。",
                    },
                    "authorization_fingerprint": authorization.allowed_combinations[
                        0
                    ].authorization_fingerprint,
                }
            ],
        )

        decision = authorization.validate_and_expand(
            "adult-watery-diarrhea-separated"
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(
            tuple(item.id for item in decision.medicines),
            ("slot-03-diosmectite", "slot-09-bifid-triple"),
        )
        self.assertEqual(
            decision.reviewed_usage_by_medicine["slot-09-bifid-triple"],
            "与蒙脱石散间隔至少 2 小时后按说明书服用。",
        )

    def test_unknown_or_stale_combination_id_fails_closed(self) -> None:
        authorization = MedicineCombinationPolicy(
            FakeCombinationRepository([self.combination])
        ).authorize(self.context, self.safe_pool)

        decision = authorization.validate_and_expand("model-invented-id")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "combination_not_authorized")
        self.assertEqual(decision.medicines, ())

    def test_unknown_red_flag_or_member_review_drift_fails_closed(self) -> None:
        missing_red_flag_assessment = self.context.__class__(
            present_facts=self.context.present_facts,
            absent_facts=frozenset(
                self.context.absent_facts - {"significant_dehydration"}
            ),
            risk_level="low",
            age_years=35,
        )
        stale_pool = [*self.safe_pool]
        stale_pool[0] = stale_pool[0].model_copy(
            update={"review_fingerprint": "new-review-03"}
        )
        policy = MedicineCombinationPolicy(
            FakeCombinationRepository([self.combination])
        )

        self.assertEqual(
            policy.authorize(
                missing_red_flag_assessment,
                self.safe_pool,
            ).allowed_combinations,
            (),
        )
        self.assertEqual(
            policy.authorize(self.context, stale_pool).allowed_combinations,
            (),
        )

    def test_legacy_reviewed_record_without_case_contract_fails_closed(self) -> None:
        legacy = ApprovedMedicineCombination(
            combination_id="legacy-unscoped-pair",
            label="旧组合",
            medicine_ids=["slot-03-diosmectite", "slot-09-bifid-triple"],
            member_identity_fingerprints={
                "slot-03-diosmectite": "identity-03",
                "slot-09-bifid-triple": "identity-09",
            },
            review_status="reviewed",
            reviewed_by="旧审核人",
            reviewed_at="2026-01-01 00:00:00",
        )

        authorization = MedicineCombinationPolicy(
            FakeCombinationRepository([legacy])
        ).authorize(self.context, self.safe_pool)

        self.assertEqual(authorization.allowed_combinations, ())

    def test_grounded_observations_build_exact_case_facts_without_treating_unknown_as_absent(
        self,
    ) -> None:
        context = combination_context_from_observations(
            [
                {
                    "concept": "水样腹泻",
                    "status": "present",
                    "evidence": "今天开始拉水样便",
                },
                {
                    "concept": "饮水情况",
                    "status": "present",
                    "evidence": "目前能喝水",
                },
                {
                    "concept": "便血",
                    "status": "absent",
                    "evidence": "没有便血",
                },
                {
                    "concept": "剧烈腹痛",
                    "status": "uncertain",
                    "evidence": "腹痛程度还不确定",
                },
            ],
            risk_level="low",
            age_years=35,
            user_evidence_texts=[
                "今天开始拉水样便，目前能喝水，没有便血，腹痛程度还不确定"
            ],
        )

        self.assertEqual(
            context.present_facts,
            frozenset({"acute_watery_diarrhea", "oral_intake_tolerated"}),
        )
        self.assertEqual(context.absent_facts, frozenset({"bloody_stool"}))
        self.assertNotIn("severe_abdominal_pain", context.absent_facts)

    def test_model_observation_without_matching_user_evidence_cannot_authorize_absence(
        self,
    ) -> None:
        context = combination_context_from_observations(
            [
                {
                    "concept": "水样腹泻",
                    "status": "present",
                    "evidence": "今天开始拉水样便",
                },
                {
                    "concept": "饮水情况",
                    "status": "present",
                    "evidence": "目前能喝水",
                },
                {
                    "concept": "黑便",
                    "status": "absent",
                    "evidence": "没有黑便",
                },
            ],
            risk_level="low",
            age_years=35,
            user_evidence_texts=["今天开始拉水样便，目前能喝水"],
        )

        self.assertEqual(
            context.present_facts,
            frozenset({"acute_watery_diarrhea", "oral_intake_tolerated"}),
        )
        self.assertEqual(context.absent_facts, frozenset())

        polarity_inverted = combination_context_from_observations(
            [
                {
                    "concept": "水样腹泻",
                    "status": "present",
                    "evidence": "水样腹泻",
                }
            ],
            risk_level="low",
            age_years=35,
            user_evidence_texts=["我没有水样腹泻"],
        )
        self.assertEqual(polarity_inverted.present_facts, frozenset())

    def test_selection_requires_exact_authorized_id_members_and_fingerprint(self) -> None:
        repository = FakeCombinationRepository([self.combination])
        authorization = MedicineCombinationPolicy(repository).authorize(
            self.context,
            self.safe_pool,
        )
        allowed = authorization.allowed_combinations[0]
        knowledge = MedicineKnowledgeRepository(medicine_repository=repository)

        accepted = knowledge.validate_ai_selection(
            {
                "options": [
                    {
                        "label": "分时方案",
                        "reason": "符合本次低风险水样腹泻条件。",
                        "combination_id": allowed.combination_id,
                        "authorization_fingerprint": allowed.authorization_fingerprint,
                        "medicine_ids": list(allowed.medicine_ids),
                        "usage_by_medicine": {
                            medicine_id: "模型不得覆盖受控用法"
                            for medicine_id in allowed.medicine_ids
                        },
                    }
                ]
            },
            self.safe_pool,
            combination_authorization=authorization,
        )

        self.assertEqual(len(accepted.options), 1)
        option = accepted.options[0]
        self.assertEqual(option.combination_id, allowed.combination_id)
        self.assertEqual(
            option.combination_authorization_fingerprint,
            allowed.authorization_fingerprint,
        )
        self.assertEqual(
            [medicine.recommended_usage for medicine in option.medicines],
            [
                self.combination.reviewed_usage_by_medicine[medicine_id]
                for medicine_id in allowed.medicine_ids
            ],
        )

        forged = knowledge.validate_ai_selection(
            {
                "options": [
                    {
                        "combination_id": allowed.combination_id,
                        "authorization_fingerprint": "stale-or-model-invented",
                        "medicine_ids": list(allowed.medicine_ids),
                    }
                ]
            },
            self.safe_pool,
            combination_authorization=authorization,
        )
        self.assertEqual(forged.options, [])
        self.assertEqual(forged.notices[0].code, "combination_not_approved")


class MedicineCombinationRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "combination-policy.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def wound_applicability(
        medicine_ids: list[str],
    ) -> MedicineCombinationApplicability:
        return MedicineCombinationApplicability(
            required_all_facts=["superficial_wound", "bleeding_controlled"],
            must_be_absent_facts=[
                "deep_wound",
                "animal_bite",
                "continued_bleeding",
                "wound_infection",
            ],
            member_required_any_facts={
                medicine_id: ["superficial_wound"] for medicine_id in medicine_ids
            },
            allowed_risk_levels=["low"],
        )

    @staticmethod
    def wound_evidence() -> list[MedicineCombinationEvidenceRef]:
        return [
            MedicineCombinationEvidenceRef(
                source_title="北京市卫生健康委员会伤口护理常识",
                source_url=(
                    "https://wjw.beijing.gov.cn/bmfw_20143/jkzs/jksh/"
                    "202602/t20260210_4505416.html"
                ),
                supports="浅表伤口清洁消毒后可按情况使用无菌纱布或创可贴。",
            )
        ]

    def test_reviewed_case_contract_persists_full_current_member_review(self) -> None:
        repository = MedicineRepository()
        medicine_ids = [
            repository.get_by_hardware_slot(17).id,
            repository.get_by_hardware_slot(22).id,
            repository.get_by_hardware_slot(20).id,
        ]

        saved = repository.save_approved_combination(
            combination_id="reviewed-superficial-wound-bandage-v1",
            label="浅表伤口消毒与创口贴覆盖",
            medicine_ids=medicine_ids,
            clinical_policy_version="case-applicability-v1",
            applicability=self.wound_applicability(medicine_ids),
            reviewed_usage_by_medicine={
                medicine_ids[0]: "清洁伤口后，按产品说明对伤口周围皮肤消毒。",
                medicine_ids[1]: "一次性使用棉签蘸取消毒液，使用后丢弃。",
                medicine_ids[2]: "待伤口干燥后按产品说明覆盖小而浅的伤口。",
            },
            evidence_refs=self.wound_evidence(),
            provenance="controlled-local-pharmacist-review",
            review_note="仅限出血已控制且无危险信号的浅表小伤口。",
            review_status="reviewed",
            reviewed_by="测试药师",
            reviewed_at="2026-08-08 16:20:00",
        )

        expected_review_fingerprints = {
            medicine_id: MedicineKnowledgeRepository.review_fingerprint(
                repository.get_by_id(medicine_id)
            )
            for medicine_id in medicine_ids
        }
        self.assertEqual(
            saved.member_review_fingerprints,
            expected_review_fingerprints,
        )
        persisted = {
            item.combination_id: item
            for item in repository.list_case_reviewed_combinations()
        }
        self.assertEqual(
            persisted["reviewed-superficial-wound-bandage-v1"],
            saved,
        )

    def test_legacy_reviewed_database_row_is_not_case_authorizable(self) -> None:
        repository = MedicineRepository()
        medicine_ids = [
            repository.get_by_hardware_slot(17).id,
            repository.get_by_hardware_slot(20).id,
        ]
        repository.save_approved_combination(
            combination_id="legacy-context-free-pair",
            label="旧版无病例约束组合",
            medicine_ids=medicine_ids,
            review_status="reviewed",
            reviewed_by="旧审核人",
            reviewed_at="2026-01-01 00:00:00",
        )

        self.assertNotIn(
            "legacy-context-free-pair",
            {
                item.combination_id
                for item in repository.list_case_reviewed_combinations()
            },
        )

    def test_three_official_evidence_combinations_are_seeded_and_enabled(self) -> None:
        repository = MedicineRepository()
        repository.list_all()

        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT combination_id, medicine_ids_json, clinical_policy_version,
                       applicability_json, member_review_fingerprints_json,
                       reviewed_usage_json, evidence_refs_json, provenance,
                       review_status, reviewed_by, reviewed_at
                FROM approved_medicine_combinations
                ORDER BY combination_id
                """
            ).fetchall()

        self.assertEqual(
            [row["combination_id"] for row in rows],
            [
                "candidate-adult-watery-diarrhea-separated-v1",
                "candidate-superficial-wound-bandage-v1",
                "candidate-superficial-wound-gauze-v1",
            ],
        )
        expected_members = {
            "candidate-adult-watery-diarrhea-separated-v1": {
                "slot-03-diosmectite",
                "slot-09-bifid-triple",
            },
            "candidate-superficial-wound-bandage-v1": {
                "slot-17-iodophor",
                "slot-20-bandage",
                "slot-22-cotton-swab",
            },
            "candidate-superficial-wound-gauze-v1": {
                "slot-10-gauze",
                "slot-17-iodophor",
                "slot-22-cotton-swab",
            },
        }
        for row in rows:
            with self.subTest(combination_id=row["combination_id"]):
                medicine_ids = json.loads(row["medicine_ids_json"])
                self.assertEqual(set(medicine_ids), expected_members[row["combination_id"]])
                self.assertEqual(row["clinical_policy_version"], "case-applicability-v1")
                self.assertEqual(row["review_status"], "reviewed")
                self.assertEqual(row["reviewed_by"], "bundled-clinical-policy-v1")
                self.assertTrue(row["reviewed_at"])
                self.assertEqual(
                    row["provenance"],
                    "official-health-guidance-bundled-v1",
                )
                self.assertEqual(
                    set(json.loads(row["member_review_fingerprints_json"])),
                    set(medicine_ids),
                )
                self.assertEqual(
                    set(json.loads(row["reviewed_usage_json"])),
                    set(medicine_ids),
                )
                self.assertTrue(json.loads(row["evidence_refs_json"]))
                applicability = json.loads(row["applicability_json"])
                self.assertEqual(
                    set(applicability["member_required_any_facts"]),
                    set(medicine_ids),
                )

        self.assertEqual(
            {item.combination_id for item in repository.list_case_reviewed_combinations()},
            {
                "candidate-adult-watery-diarrhea-separated-v1",
                "candidate-superficial-wound-bandage-v1",
                "candidate-superficial-wound-gauze-v1",
            },
        )


if __name__ == "__main__":
    unittest.main()
