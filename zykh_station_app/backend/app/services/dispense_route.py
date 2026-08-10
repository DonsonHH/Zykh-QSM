from __future__ import annotations

from typing import Literal

from ..schemas.dispense import DispenseConfirmRequest


DispenseRoute = Literal["PLAN", "INQUIRY", "MANUAL_INVENTORY"]


def classify_dispense_route(request: DispenseConfirmRequest) -> DispenseRoute:
    """Classify a dispense request from server-recognized request credentials."""
    if request.verification_method.strip() == "inquiry_confirmed":
        return "INQUIRY"
    if request.today_plan_id.strip():
        return "PLAN"
    return "MANUAL_INVENTORY"
