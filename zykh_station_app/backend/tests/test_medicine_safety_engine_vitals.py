from __future__ import annotations

import unittest

from app.schemas.inquiry import InquiryExtractedInformation
from app.services.medicine_safety_engine import MedicineSafetyEngine


class MedicineSafetyEngineVitalsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MedicineSafetyEngine()
        self.case = InquiryExtractedInformation(symptoms_text="轻微头晕")

    def test_reliable_core_spo2_triggers_emergency_guard(self) -> None:
        decision = self.engine.assess_guardrails(
            self.case,
            {
                "core": {
                    "spo2": {
                        "value": 88,
                        "unit": "%",
                        "usable": True,
                        "quality": "measured",
                    }
                }
            },
        )

        self.assertEqual(decision.risk_level, "emergency")

    def test_unreliable_core_spo2_does_not_trigger_guard(self) -> None:
        decision = self.engine.assess_guardrails(
            self.case,
            {
                "core": {
                    "spo2": {
                        "value": 88,
                        "unit": "%",
                        "usable": False,
                        "quality": "signal_unreliable",
                    }
                }
            },
        )

        self.assertEqual(decision.risk_level, "low")

    def test_reference_metrics_never_trigger_hard_guard(self) -> None:
        decision = self.engine.assess_guardrails(
            self.case,
            {
                "core": {},
                "reference": {
                    "body_temperature": {
                        "value": 42,
                        "unit": "℃",
                        "usable": True,
                        "quality": "reference_only",
                    },
                    "blood_pressure": {
                        "value": "210/130",
                        "unit": "mmHg",
                        "usable": True,
                        "quality": "reference_only",
                    },
                },
            },
        )

        self.assertEqual(decision.risk_level, "low")

    def test_legacy_flat_vitals_remain_compatible(self) -> None:
        decision = self.engine.assess_guardrails(self.case, {"spo2": 88})

        self.assertEqual(decision.risk_level, "emergency")


if __name__ == "__main__":
    unittest.main()
