from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.inquiry import InquiryVitalsRequest  # noqa: E402
from app.services.vitals_evidence_service import VitalsEvidenceService  # noqa: E402


class VitalsEvidenceServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = VitalsEvidenceService()

    def test_stable_device_result_separates_core_and_reference_metrics(self) -> None:
        evidence = self.service.build(
            InquiryVitalsRequest(
                measurement_session_id="vitals-1",
                status="complete",
                temperature=36.7,
                heart_rate=78,
                spo2=98,
                body_temperature=34.6,
                systolic_pressure=121,
                diastolic_pressure=78,
                hrv_sdnn=42,
                quality="stable",
                finger_detected=True,
                heart_rate_frame_count=8,
                spo2_frame_count=7,
                source="UART8-vitals-24B+GY-614",
            )
        )

        self.assertTrue(evidence.core["temperature"].usable)
        self.assertTrue(evidence.core["heart_rate"].usable)
        self.assertTrue(evidence.core["spo2"].usable)
        self.assertEqual(evidence.reference["blood_pressure"].value, "121/78")
        self.assertEqual(evidence.reference["hrv_sdnn"].quality, "reference_only")
        self.assertTrue(evidence.quality["core_ready"])

    def test_low_spo2_without_finger_contact_is_not_usable(self) -> None:
        evidence = self.service.build(
            InquiryVitalsRequest(
                status="partial",
                temperature=36.5,
                heart_rate=72,
                spo2=88,
                quality="no_finger",
                finger_detected=False,
                heart_rate_frame_count=1,
                spo2_frame_count=1,
            )
        )

        self.assertTrue(evidence.core["temperature"].usable)
        self.assertFalse(evidence.core["heart_rate"].usable)
        self.assertFalse(evidence.core["spo2"].usable)
        self.assertFalse(evidence.quality["core_ready"])

    def test_failed_measurement_is_preserved_without_inventing_values(self) -> None:
        evidence = self.service.build(
            InquiryVitalsRequest(
                measurement_session_id="vitals-2",
                status="failed",
                quality="error",
                error_message="未检测到稳定手指信号",
            )
        )

        self.assertEqual(evidence.measurement_status, "failed")
        self.assertEqual(evidence.core, {})
        self.assertFalse(evidence.quality["core_ready"])
        self.assertIn("未完成", evidence.reliability_notes[0])


if __name__ == "__main__":
    unittest.main()
