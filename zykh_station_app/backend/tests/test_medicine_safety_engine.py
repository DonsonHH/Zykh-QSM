from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import InquiryExtractedInformation  # noqa: E402
from app.services.medicine_safety_engine import MedicineSafetyEngine  # noqa: E402


class MedicineSafetyEngineVitalsTruthTest(unittest.TestCase):
    def test_volunteered_instability_is_a_high_risk_fact(self) -> None:
        for symptom in ("我突然走路不稳", "扭伤后这只脚完全不能负重"):
            with self.subTest(symptom=symptom):
                decision = MedicineSafetyEngine().assess_guardrails(
                    InquiryExtractedInformation(symptoms_text=symptom),
                    None,
                )

                self.assertEqual(decision.risk_level, "high")
                self.assertIn("出现持续或严重危险表现", decision.risk_reasons)

    def test_negated_instability_does_not_raise_risk(self) -> None:
        decision = MedicineSafetyEngine().assess_guardrails(
            InquiryExtractedInformation(symptoms_text="没有走路不稳，可以正常负重"),
            None,
        )

        self.assertEqual(decision.risk_level, "low")

    def test_historical_reference_values_do_not_drive_current_risk(self) -> None:
        decision = MedicineSafetyEngine().assess_guardrails(
            InquiryExtractedInformation(symptoms_text="轻微鼻塞"),
            {
                "status": "failed",
                "historical_fallback": True,
                "historical_temperature": 42.0,
                "historical_heart_rate": 180,
                "historical_spo2": 50,
            },
        )

        self.assertEqual(decision.risk_level, "low")
        self.assertEqual(decision.risk_reasons, ["未触发硬性危险信号"])

    def test_ungrounded_model_risk_raise_fails_closed_with_an_auditable_reason(self) -> None:
        decision = MedicineSafetyEngine().assess_guardrails(
            InquiryExtractedInformation(symptoms_text="轻微鼻塞"),
            None,
            ai_risk_level="high",
            ai_risk_reasons=[],
            trusted_evidence_texts=["只是有点轻微鼻塞"],
        )

        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(
            decision.risk_reasons,
            ["风险判断提示高风险，但未提供可与本次用户原话核对的依据；本次停止自动取药"],
        )

    def test_grounded_model_risk_raise_keeps_the_matching_user_reason(self) -> None:
        decision = MedicineSafetyEngine().assess_guardrails(
            InquiryExtractedInformation(symptoms_text="口干、尿量明显减少"),
            None,
            ai_risk_level="high",
            ai_risk_reasons=["明显脱水"],
            trusted_evidence_texts=["我感觉有明显脱水"],
        )

        self.assertEqual(decision.risk_level, "high")
        self.assertIn("明显脱水", decision.risk_reasons)


if __name__ == "__main__":
    unittest.main()
