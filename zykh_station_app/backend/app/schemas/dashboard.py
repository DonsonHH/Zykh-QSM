from __future__ import annotations

from pydantic import BaseModel

from .site import SiteProfile
from .status import StatusChip


class MedicationSummary(BaseModel):
    pending_people: int
    pending_plans: int
    next_time: str
    featured_subject: str
    featured_medicine: str


class InquirySummary(BaseModel):
    title: str
    description: str
    action_label: str


class QuickAction(BaseModel):
    id: str
    title: str
    subtitle: str
    tone: str


class StationStat(BaseModel):
    id: str
    label: str
    value: str
    unit: str = ""
    tone: str = "soft"


class DashboardPayload(BaseModel):
    ok: bool = True
    site: SiteProfile
    chips: list[StatusChip]
    medication: MedicationSummary
    inquiry: InquirySummary
    quick_actions: list[QuickAction]
    stats: list[StationStat]
    safety_notice: str
    updated_at: str
