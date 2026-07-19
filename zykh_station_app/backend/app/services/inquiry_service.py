from __future__ import annotations

from uuid import uuid4

from ..db import now_text
from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.inquiry import InquiryEvaluateRequest, InquiryExtractedInformation, InquiryResult
from .ai_service import AiService
from .medicine_safety_engine import MedicineSafetyEngine
from .symptom_interpreter import SymptomInterpreter


class InquiryService:
    """Compatibility facade for the phase-three evaluate API."""

    def __init__(
        self,
        repository: InquiryRepository | None = None,
        ai_service: AiService | None = None,
        safety_engine: MedicineSafetyEngine | None = None,
    ) -> None:
        self.repository = repository or InquiryRepository()
        self.ai_service = ai_service or AiService()
        self.interpreter = SymptomInterpreter(self.ai_service)
        self.safety_engine = safety_engine or MedicineSafetyEngine()

    def evaluate(self, request: InquiryEvaluateRequest) -> InquiryResult:
        transcript = "；".join(
            item.strip()
            for item in (
                request.symptoms_text,
                request.duration,
                request.used_medicines,
                request.allergy_or_contraindication,
            )
            if item.strip()
        )
        interpretation = self.interpreter.interpret(transcript, {}, {})
        extracted = InquiryExtractedInformation(
            case_summary=interpretation.case_summary,
            observations=interpretation.observations,
            uncertainties=interpretation.uncertainties,
            history_relationship=interpretation.history_relationship,
            ai_risk_level=interpretation.ai_risk_level,
            ai_risk_reasons=interpretation.risk_signals,
            ai_available=interpretation.available,
            symptom_dimensions=interpretation.symptom_dimensions,
            dimension_evidence=interpretation.dimension_evidence,
            symptoms_text=request.symptoms_text,
            duration=request.duration or interpretation.duration,
            used_medicines=request.used_medicines or interpretation.used_medicines,
            allergy_or_contraindication=(
                request.allergy_or_contraindication or interpretation.allergy_or_contraindication
            ),
            confidence=interpretation.confidence,
        )
        guard = self.safety_engine.assess_guardrails(
            extracted,
            None,
            ai_risk_level=interpretation.ai_risk_level,
            ai_risk_reasons=interpretation.risk_signals,
        )
        options = []
        if (
            guard.risk_level in {"low", "medium"}
            and interpretation.available
            and extracted.used_medicines not in {"", "不确定"}
            and extracted.allergy_or_contraindication not in {"", "不确定"}
        ):
            safe_pool = self.safety_engine.knowledge.safe_candidate_pool(
                extracted.allergy_or_contraindication
            )
            ranking = self.interpreter.rank_candidates(
                {
                    "case_summary": extracted.case_summary,
                    "observations": [value.model_dump() for value in extracted.observations],
                    "duration": extracted.duration,
                    "used_medicines": extracted.used_medicines,
                    "allergy_or_contraindication": extracted.allergy_or_contraindication,
                    "risk_level": guard.risk_level,
                },
                [candidate.model_dump() for candidate in safe_pool],
            )
            if ranking.get("ok"):
                options = self.safety_engine.knowledge.options_from_ai_selection(ranking, safe_pool)
        candidates = [
            medicine
            for option in options[:2]
            for medicine in option.medicines[:1]
        ]
        can_view = guard.risk_level in {"low", "medium"} and bool(candidates)
        categories = list(dict.fromkeys(candidate.category for candidate in candidates))
        warnings = []
        allergy = extracted.allergy_or_contraindication.strip()
        if allergy and allergy not in {"无", "没有", "不确定"}:
            warnings.append(f"已记录过敏/禁忌信息：{allergy}")
        risk_label = {
            "low": "低风险",
            "medium": "中风险",
            "high": "高风险",
            "emergency": "紧急风险",
        }[guard.risk_level]
        if guard.risk_level == "emergency":
            notice = "存在紧急危险信号，请立即联系医生或救援人员。"
            steps = ["停止自行取药", "立即联系医生或救援人员", "保持有人陪同"]
        elif guard.risk_level == "high":
            notice = "存在高风险信号，本次不展示候选药品。"
            steps = ["尽快联系医生或现场协助人员", "不要自行新增用药"]
        elif can_view:
            notice = "可查看候选药品及安全提示；主候选与备选为二选一，不表示联合使用。"
            steps = ["查看候选药品说明", "在药品页完成原有用药安全核验"]
        else:
            notice = "当前库存中没有通过核验的候选药品，请联系医生或家人协助。"
            steps = ["补充信息或联系医生"]
        result = InquiryResult(
            inquiry_id=f"inquiry-{uuid4().hex[:12]}",
            risk_level=guard.risk_level,
            risk_label=risk_label,
            symptoms_summary=transcript,
            suggested_categories=categories,
            candidate_medicines=candidates,
            contraindication_warnings=warnings,
            safety_notice=notice,
            next_steps=steps,
            can_proceed_to_dispense=can_view,
            created_at=now_text(),
            ai_source=interpretation.source,
            ai_message="问询模型整理病例；硬性风险、库存、有效期和禁忌由本地程序复核。",
        )
        return self.repository.append(result)

    def get_result(self, inquiry_id: str) -> InquiryResult | None:
        return self.repository.get_by_id(inquiry_id)

    def list_records(self) -> list[InquiryResult]:
        return self.repository.list_records()

    @staticmethod
    def _safe_ai_notice(value: object) -> str:
        notice = str(value or "").strip()
        if not notice:
            return ""
        definitive_claims = (
            "无禁忌",
            "没有禁忌",
            "可以服用",
            "可安全服用",
            "安全服用",
            "建议服用",
            "应该服用",
            "无需就医",
        )
        return "" if any(claim in notice for claim in definitive_claims) else notice
