from __future__ import annotations

from dataclasses import dataclass, field

from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.inquiry import InquirySessionResponse


@dataclass(frozen=True)
class InquiryHistoryItem:
    session_id: str
    happened_at: str
    title: str
    case_summary: str
    risk_level: str
    outcome: str

    def model_context(self) -> dict[str, str]:
        return {
            "date": self.happened_at,
            "title": self.title,
            "case_summary": self.case_summary,
            "risk_level": self.risk_level,
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class InquiryHistoryContext:
    recent: list[InquiryHistoryItem] = field(default_factory=list)

    @property
    def has_history(self) -> bool:
        return bool(self.recent)

    @property
    def has_similar_history(self) -> bool:
        return False

    @property
    def medicine_counts(self) -> dict[str, int]:
        return {}

    def model_context(self) -> list[dict[str, str]]:
        return [item.model_context() for item in self.recent]


class InquiryHistoryService:
    """Provides bounded natural-language history; the model decides semantic relation."""

    def __init__(self, repository: InquiryRepository | None = None) -> None:
        self.repository = repository or InquiryRepository()

    def context_for(
        self,
        user_id: str,
        current_session_id: str,
        _legacy_dimensions: list[str] | None = None,
    ) -> InquiryHistoryContext:
        if not user_id:
            return InquiryHistoryContext()
        items = [
            self._history_item(session)
            for session in self.repository.list_user_sessions(
                user_id,
                exclude_session_id=current_session_id,
                limit=6,
            )
        ]
        return InquiryHistoryContext(recent=items)

    @staticmethod
    def _history_item(session: InquirySessionResponse) -> InquiryHistoryItem:
        extracted = session.extracted_information
        case_summary = (
            extracted.case_summary.strip()
            or session.reasoning_summary.strip()
            or extracted.symptoms_text.strip()
            or "未形成病例摘要"
        )
        if session.action_status == "complete":
            outcome = "已完成用户确认的取药流程"
        elif session.can_view_medicines:
            outcome = "已展示候选药品信息"
        elif session.risk_level in {"high", "emergency"}:
            outcome = "已建议联系医生或现场协助人员"
        else:
            outcome = "问询已记录"
        return InquiryHistoryItem(
            session_id=session.session_id,
            happened_at=session.updated_at,
            title=session.title,
            case_summary=case_summary[:240],
            risk_level=session.risk_level or "",
            outcome=outcome,
        )
