from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.dispense import DispenseConfirmRequest  # noqa: E402
from app.services.dispense_route import classify_dispense_route  # noqa: E402


class DispenseRouteTest(unittest.TestCase):
    @staticmethod
    def _request(**updates: object) -> DispenseConfirmRequest:
        values: dict[str, object] = {
            "medicine_id": "slot-13-ibuprofen",
            "slot": "S13",
            "quantity": 1,
            "reason": "route classification test",
            "confirmed_safety_notice": True,
        }
        values.update(updates)
        return DispenseConfirmRequest.model_validate(values)

    def test_inquiry_marker_cannot_be_hidden_behind_a_today_plan_id(self) -> None:
        request = self._request(
            today_plan_id="plan-demo-wang-ibuprofen",
            verification_method="inquiry_confirmed",
            expected_review_fingerprint="review-fingerprint",
        )

        self.assertEqual(classify_dispense_route(request), "INQUIRY")

    def test_public_confirm_rejects_inquiry_marker_even_with_a_plan_id(self) -> None:
        from app.routers.dispense import confirm_dispense

        request = self._request(
            today_plan_id="plan-demo-wang-ibuprofen",
            verification_method="inquiry_confirmed",
            expected_review_fingerprint="publicly-visible-fingerprint",
        )

        with patch(
            "app.routers.dispense.DispenseService",
            side_effect=AssertionError("public request reached the cabinet service"),
        ):
            with self.assertRaises(HTTPException) as raised:
                confirm_dispense(request)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("问询会话", str(raised.exception.detail))

    def test_inquiry_confirmation_without_a_plan_is_inquiry(self) -> None:
        request = self._request(
            verification_method="inquiry_confirmed",
            expected_review_fingerprint="review-fingerprint",
        )

        self.assertEqual(classify_dispense_route(request), "INQUIRY")

    def test_public_confirm_endpoint_cannot_forge_an_inquiry_confirmation(self) -> None:
        from app.routers.dispense import confirm_dispense

        request = self._request(
            verification_method="inquiry_confirmed",
            expected_review_fingerprint="publicly-visible-fingerprint",
            target_user_id="li-yeye",
        )

        with patch(
            "app.routers.dispense.DispenseService",
            side_effect=AssertionError("public request reached the cabinet service"),
        ):
            with self.assertRaises(HTTPException) as raised:
                confirm_dispense(request)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("问询会话", str(raised.exception.detail))

    def test_all_other_identity_methods_are_manual_even_with_a_forged_route(self) -> None:
        for verification_method in (
            "face",
            "fingerprint",
            "guest",
            "face_guest_confirmed",
            "manual",
        ):
            with self.subTest(verification_method=verification_method):
                request = self._request(
                    today_plan_id="   ",
                    verification_method=verification_method,
                    route="PLAN",
                )

                self.assertEqual(
                    classify_dispense_route(request),
                    "MANUAL_INVENTORY",
                )


if __name__ == "__main__":
    unittest.main()
