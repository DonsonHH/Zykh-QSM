from __future__ import annotations

from uuid import uuid4

from ..db import now_text
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.inquiry import InquiryEvaluateRequest, InquiryResult
from .rules_engine import RulesEngine


class InquiryService:
    def __init__(
        self,
        repository: InquiryRepository | None = None,
        rules_engine: RulesEngine | None = None,
    ) -> None:
        self.repository = repository or InquiryRepository()
        self.rules_engine = rules_engine or RulesEngine()

    def evaluate(self, request: InquiryEvaluateRequest) -> InquiryResult:
        evaluation = self.rules_engine.evaluate(request)
        result = InquiryResult(
            inquiry_id=f"inquiry-{uuid4().hex[:12]}",
            risk_level=evaluation.risk_level,
            risk_label=evaluation.risk_label,
            symptoms_summary=evaluation.symptoms_summary,
            suggested_categories=evaluation.suggested_categories,
            candidate_medicines=evaluation.candidate_medicines,
            contraindication_warnings=evaluation.contraindication_warnings,
            safety_notice=evaluation.safety_notice,
            next_steps=evaluation.next_steps,
            can_proceed_to_dispense=evaluation.can_proceed_to_dispense,
            created_at=now_text(),
        )
        return self.repository.append(result)

    def get_result(self, inquiry_id: str) -> InquiryResult | None:
        return self.repository.get_by_id(inquiry_id)

    def list_records(self) -> list[InquiryResult]:
        return self.repository.list_records()
