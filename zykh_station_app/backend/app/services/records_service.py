from __future__ import annotations

from .. import db
from ..repositories.device_action_repository import DeviceActionRepository
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.inquiry_repository import InquiryRepository
from ..repositories.vitals_repository import VitalsRepository
from ..schemas.records import RecentRecord, RecordsSummary, ServiceUser, TodayPlan
from .sync_service import SyncService


class RecordsService:
    def __init__(
        self,
        inquiry_repository: InquiryRepository | None = None,
        dispense_repository: DispenseRepository | None = None,
        device_action_repository: DeviceActionRepository | None = None,
        sync_service: SyncService | None = None,
    ) -> None:
        self.inquiry_repository = inquiry_repository or InquiryRepository()
        self.dispense_repository = dispense_repository or DispenseRepository()
        self.device_action_repository = device_action_repository or DeviceActionRepository()
        self.sync_service = sync_service or SyncService()
        self.vitals_repository = VitalsRepository()

    def get_summary(self) -> RecordsSummary:
        sync_status = self.sync_service.get_status()
        return RecordsSummary(
            today_service_users=len(self.list_service_users()),
            pending_sync_count=sync_status.pending_count,
            local_record_count=len(self.dispense_repository.list_records()),
            today_plan_count=len(self.list_today_plans()),
        )

    def get_recent_records(self) -> list[RecentRecord]:
        sync_status = self.sync_service.get_status()
        records = self._dispense_records(sync_status.sync_status)
        return sorted(records, key=lambda record: record.time, reverse=True)[:8]

    def list_service_users(self) -> list[ServiceUser]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, age, profile, note, status FROM service_users ORDER BY id"
            ).fetchall()
        return [ServiceUser(**dict(row)) for row in rows]

    def list_today_plans(self) -> list[TodayPlan]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, time, medicine, status, target_user FROM today_plans ORDER BY time"
            ).fetchall()
        return [TodayPlan(**dict(row)) for row in rows]

    def _inquiry_records(self, sync_status: str) -> list[RecentRecord]:
        return [
            RecentRecord(
                id=record.inquiry_id,
                time=self._time_part(record.created_at),
                type="AI应急问询",
                title=record.risk_label,
                description=f"{record.symptoms_summary[:38]}",
                target_user="王五",
                status="已评估",
                sync_status=sync_status,
            )
            for record in self.inquiry_repository.list_records()
        ]

    def _dispense_records(self, sync_status: str) -> list[RecentRecord]:
        return [
            RecentRecord(
                id=record.id,
                time=self._time_part(record.created_at),
                type="取药记录",
                title=f"张三取走{record.medicine_name}",
                description=f"{record.quantity}{record.unit}",
                target_user="张三",
                status="已记录" if record.qsm_ok or record.dry_run else "失败",
                sync_status=sync_status,
            )
            for record in self.dispense_repository.list_records()
        ]

    def _device_records(self, sync_status: str) -> list[RecentRecord]:
        return [
            RecentRecord(
                id=record.id,
                time=self._time_part(record.created_at),
                type=record.type,
                title=record.title,
                description=record.description,
                target_user=record.target_user,
                status=record.status,
                sync_status=sync_status,
            )
            for record in self.device_action_repository.list_records()
        ]

    @staticmethod
    def _time_part(value: str) -> str:
        if " " in value:
            return value.split(" ", 1)[1][:5]
        return value[:5] or "--:--"
