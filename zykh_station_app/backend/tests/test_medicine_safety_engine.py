from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import InquiryExtractedInformation  # noqa: E402
from app.services.medicine_safety_engine import MedicineSafetyEngine  # noqa: E402


class MedicineSafetyEngineVitalsTruthTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
