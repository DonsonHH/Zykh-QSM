from __future__ import annotations

from ..schemas.manual_medication_access import (
    ManualDispenseExecutionCommand,
    ManualDispenseExecutionResult,
)
from .dispense_service import DispenseService


class DispenseServiceManualAdapter:
    """The sole physical-dispense seam used after a one-time manual safety pass."""

    def __init__(self, dispense_service: DispenseService | None = None) -> None:
        self.dispense_service = dispense_service or DispenseService()

    def confirm_manual(
        self,
        command: ManualDispenseExecutionCommand,
    ) -> ManualDispenseExecutionResult:
        response = self.dispense_service.confirm_checked_manual(command)
        if response.result_unknown:
            status = "RESULT_UNKNOWN"
        elif response.ok and not response.dry_run:
            status = "DISPENSED"
        else:
            status = "HARDWARE_FAILED"
        return ManualDispenseExecutionResult(
            dispense_status=status,
            message=response.message,
            dispense_record_id=str(response.record_id or ""),
        )
