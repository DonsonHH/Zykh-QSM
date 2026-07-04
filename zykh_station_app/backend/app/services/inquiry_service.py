from __future__ import annotations

from uuid import uuid4

from ..db import now_text
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.inquiry import InquiryEvaluateRequest, InquiryResult
from .ai_service import AiService
from .rules_engine import RulesEngine


RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "emergency": 3}


class InquiryService:
    def __init__(
        self,
        repository: InquiryRepository | None = None,
        rules_engine: RulesEngine | None = None,
        ai_service: AiService | None = None,
    ) -> None:
        self.repository = repository or InquiryRepository()
        self.rules_engine = rules_engine or RulesEngine()
        self.ai_service = ai_service or AiService()

    def evaluate(self, request: InquiryEvaluateRequest) -> InquiryResult:
        evaluation = self.rules_engine.evaluate(request)
        ai = self.ai_service.evaluate_inquiry(request)
        ai_ok = bool(ai.get("ok"))

        risk_level = evaluation.risk_level
        risk_label = evaluation.risk_label
        symptoms_summary = evaluation.symptoms_summary
        suggested_categories = evaluation.suggested_categories
        contraindication_warnings = evaluation.contraindication_warnings
        safety_notice = evaluation.safety_notice
        next_steps = evaluation.next_steps
        can_proceed = evaluation.can_proceed_to_dispense

        if ai_ok:
            ai_risk = str(ai.get("risk_level") or "").strip()
            if ai_risk in RISK_ORDER and RISK_ORDER[ai_risk] > RISK_ORDER[risk_level]:
                risk_level = ai_risk
                risk_label = str(ai.get("risk_label") or self.rules_engine._risk_label(risk_level))
            symptoms_summary = str(ai.get("symptoms_summary") or symptoms_summary)
            ai_categories = [str(item) for item in ai.get("suggested_categories", []) if str(item).strip()]
            if ai_categories:
                suggested_categories = ai_categories[:3]
            ai_warnings = [str(item) for item in ai.get("contraindication_warnings", []) if str(item).strip()]
            if ai_warnings:
                contraindication_warnings = list(dict.fromkeys([*contraindication_warnings, *ai_warnings]))
            safety_notice = str(ai.get("safety_notice") or safety_notice)
            ai_steps = [str(item) for item in ai.get("next_steps", []) if str(item).strip()]
            if ai_steps:
                next_steps = ai_steps[:4]
            can_proceed = (
                can_proceed
                and bool(ai.get("can_proceed_to_dispense"))
                and risk_level == "low"
                and not contraindication_warnings
            )

        candidate_medicines = self.rules_engine.candidate_medicines_for(
            suggested_categories,
            request.allergy_or_contraindication,
        )
        has_stock = any(medicine.stock > 0 for medicine in candidate_medicines)
        can_proceed = can_proceed and has_stock

        result = InquiryResult(
            inquiry_id=f"inquiry-{uuid4().hex[:12]}",
            risk_level=risk_level,
            risk_label=risk_label,
            symptoms_summary=symptoms_summary,
            suggested_categories=suggested_categories,
            candidate_medicines=candidate_medicines,
            contraindication_warnings=contraindication_warnings,
            safety_notice=safety_notice,
            next_steps=next_steps,
            can_proceed_to_dispense=can_proceed,
            created_at=now_text(),
            ai_source=str(ai.get("source") or "local_fallback"),
            ai_message=str(ai.get("message") or "本地规则兜底"),
        )
        return self.repository.append(result)

    def get_result(self, inquiry_id: str) -> InquiryResult | None:
        return self.repository.get_by_id(inquiry_id)

    def list_records(self) -> list[InquiryResult]:
        return self.repository.list_records()
