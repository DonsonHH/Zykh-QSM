from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..repositories.inquiry_repository import InquiryRepository
from ..schemas.inquiry import InquirySessionResponse


@dataclass(frozen=True)
class InquiryHistoryContext:
    similar_session_count: int = 0
    medicine_counts: dict[str, int] = field(default_factory=dict)
    dimension_counts: dict[str, int] = field(default_factory=dict)
    last_matching_title: str = ""

    @property
    def has_similar_history(self) -> bool:
        return self.similar_session_count > 0


class InquiryHistoryService:
    """Turns prior completed sessions into bounded context, never a safety override."""

    def __init__(self, repository: InquiryRepository | None = None) -> None:
        self.repository = repository or InquiryRepository()

    def context_for(
        self,
        user_id: str,
        current_session_id: str,
        dimensions: list[str],
    ) -> InquiryHistoryContext:
        if not user_id or not dimensions:
            return InquiryHistoryContext()
        current_dimensions = set(dimensions)
        matching: list[InquirySessionResponse] = []
        dimension_counts: Counter[str] = Counter()
        medicine_counts: Counter[str] = Counter()
        for session in self.repository.list_user_sessions(
            user_id,
            exclude_session_id=current_session_id,
            limit=12,
        ):
            prior_dimensions = set(session.extracted_information.symptom_dimensions)
            if not current_dimensions.intersection(prior_dimensions):
                continue
            matching.append(session)
            dimension_counts.update(current_dimensions.intersection(prior_dimensions))
            medicine_counts.update(self._successfully_selected_medicines(session))
        return InquiryHistoryContext(
            similar_session_count=len(matching),
            medicine_counts=dict(medicine_counts),
            dimension_counts=dict(dimension_counts),
            last_matching_title=matching[0].title if matching else "",
        )

    @staticmethod
    def _successfully_selected_medicines(session: InquirySessionResponse) -> list[str]:
        successful = [
            str(item.get("medicine_id") or "")
            for item in session.action_items
            if item.get("ok") and item.get("medicine_id")
        ]
        if successful:
            return successful
        if session.action_status not in {"complete", "partial"} or not session.selected_option_id:
            return []
        selected = next(
            (option for option in session.treatment_options if option.option_id == session.selected_option_id),
            None,
        )
        return [medicine.id for medicine in selected.medicines] if selected else []
