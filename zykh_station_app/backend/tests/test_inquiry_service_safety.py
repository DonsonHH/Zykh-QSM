from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import InquiryEvaluateRequest, InquiryObservation  # noqa: E402
from app.schemas.medicine import Medicine  # noqa: E402
from app.services.inquiry_service import InquiryService  # noqa: E402
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.medicine_safety_engine import MedicineSafetyEngine  # noqa: E402
from app.services.symptom_interpreter import SymptomInterpretation  # noqa: E402


def ibuprofen(stock: int = 1) -> Medicine:
    return Medicine(
        id="slot-13-ibuprofen",
        slot="S13",
        hardware_slot=13,
        barcode="6913991301572",
        manufacturer="芬必得",
        name="布洛芬缓释胶囊",
        category="解热镇痛",
        tags=["芬必得", "头痛"],
        indications="用于缓解轻至中度疼痛",
        dosage="成人一次1粒，一日2次",
        contraindications=["非甾体抗炎药过敏者禁用"],
        stock=stock,
        unit="盒",
        expire_date="2030-12",
        image_hint="芬必得 布洛芬缓释胶囊",
        is_otc=True,
        is_emergency=False,
        safety_note="避免与其他解热镇痛药重复使用",
        aliases=["芬必得", "布洛芬"],
        active_ingredients=["布洛芬"],
        guidance_source="verified_label",
        guidance_review_required=False,
        package_verified=True,
        safety_review_status="reviewed",
        safety_reviewed_by="test-pharmacist",
        safety_reviewed_at="2026-08-08T00:00:00+08:00",
    )


class SequenceMedicineRepository:
    def __init__(self, snapshots: list[list[Medicine]]) -> None:
        self.snapshots = snapshots
        self.calls = 0

    def list_all(self) -> list[Medicine]:
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


class MemoryInquiryRepository:
    def append(self, result):
        return result


class RankingInterpreter:
    def __init__(self) -> None:
        self.ranked_candidates: list[list[dict]] = []

    def interpret(self, transcript, _existing, _profile):
        return SymptomInterpretation(
            case_summary="用户头痛。",
            observations=[
                InquiryObservation(
                    concept="头痛",
                    status="present",
                    evidence="轻微头痛",
                    source_turn=1,
                    confidence=0.9,
                )
            ],
            duration="半天",
            used_medicines="未使用",
            allergy_or_contraindication="无",
            action_intent="analyze",
            ai_risk_level="low",
            clinical_ready=True,
            confidence=0.9,
            source="cloud",
            available=True,
        )

    def rank_candidates(self, _context, candidates):
        self.ranked_candidates.append(candidates)
        ids = [candidate["id"] for candidate in candidates[:1]]
        return {
            "ok": True,
            "source": "cloud",
            "options": [{"medicine_ids": ids, "reason": "与当前疼痛相关。"}] if ids else [],
        }


class InquiryServiceSafetyTest(unittest.TestCase):
    def service(self, snapshots: list[list[Medicine]]):
        source = SequenceMedicineRepository(snapshots)
        knowledge = MedicineKnowledgeRepository(source)
        service = InquiryService(
            repository=MemoryInquiryRepository(),
            safety_engine=MedicineSafetyEngine(knowledge),
        )
        interpreter = RankingInterpreter()
        service.interpreter = interpreter
        return service, interpreter, source

    def test_one_shot_evaluate_filters_current_episode_brand_alias(self) -> None:
        service, interpreter, _ = self.service([[ibuprofen()]])

        result = service.evaluate(
            InquiryEvaluateRequest(
                symptoms_text="轻微头痛",
                duration="半天",
                used_medicines="芬必得",
                allergy_or_contraindication="无",
            )
        )

        self.assertEqual(result.candidate_medicines, [])
        self.assertEqual(interpreter.ranked_candidates, [[]])
        self.assertEqual(
            [notice.code for notice in result.medication_safety_notices],
            ["used_medicine_duplicate"],
        )
        self.assertIn("布洛芬缓释胶囊", result.medication_safety_notices[0].message)

    def test_one_shot_evaluate_revalidates_inventory_after_ranking(self) -> None:
        service, _, source = self.service([[ibuprofen(1)], [ibuprofen(0)]])

        result = service.evaluate(
            InquiryEvaluateRequest(
                symptoms_text="轻微头痛",
                duration="半天",
                used_medicines="未使用",
                allergy_or_contraindication="无",
            )
        )

        self.assertEqual(source.calls, 2)
        self.assertEqual(result.candidate_medicines, [])


if __name__ == "__main__":
    unittest.main()
