from __future__ import annotations

import re

from .. import db
from ..repositories.device_action_repository import DeviceActionRepository
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.inquiry_repository import InquiryRepository
from ..repositories.vitals_repository import VitalsRepository
from ..schemas.records import RecentRecord, RecordsSummary, ServiceUser, ServiceUserCreateRequest, ServiceUserUpdateRequest, TodayPlan
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
                "SELECT id, name, age, profile, allergies, note, status FROM service_users ORDER BY id"
            ).fetchall()
        return [ServiceUser(**dict(row)) for row in rows]

    def create_service_user(self, request: ServiceUserCreateRequest) -> ServiceUser:
        db.init_db()
        name = request.name.strip()[:12] or "新使用人"
        age = max(0, min(int(request.age or 0), 120))
        profile = request.profile.strip()[:80] or "待补充"
        allergies = request.allergies.strip()[:80]
        note = request.note.strip()[:120] or "AI问询新建"
        status = request.status.strip()[:20] or "待完善"
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", name) or "user"
        user_id = f"user-{slug}-{db.now_text().replace(' ', '-').replace(':', '')}"
        with db.connect() as conn:
            existing = conn.execute("SELECT id, name, age, profile, allergies, note, status FROM service_users WHERE name=?", (name,)).fetchone()
            if existing:
                return ServiceUser(**dict(existing))
            conn.execute(
                """
                INSERT INTO service_users(id, name, age, profile, allergies, note, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, name, age, profile, allergies, note, status),
            )
        return ServiceUser(id=user_id, name=name, age=age, profile=profile, allergies=allergies, note=note, status=status)

    def update_service_user(self, user_id: str, request: ServiceUserUpdateRequest) -> ServiceUser:
        db.init_db()
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT id, name, age, profile, allergies, note, status FROM service_users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not existing:
                raise ValueError("服务对象不存在")

            current = dict(existing)
            name = (request.name if request.name is not None else current["name"]).strip()[:12] or "新使用人"
            age_value = request.age if request.age is not None else current["age"]
            age = max(0, min(int(age_value or 0), 120))
            profile = (request.profile if request.profile is not None else current["profile"]).strip()[:80] or "待补充"
            allergies = (request.allergies if request.allergies is not None else current["allergies"]).strip()[:80]
            note = (request.note if request.note is not None else current["note"]).strip()[:120]
            status = (request.status if request.status is not None else current["status"]).strip()[:20] or "待完善"

            duplicate = conn.execute(
                "SELECT id FROM service_users WHERE name=? AND id<>?",
                (name, user_id),
            ).fetchone()
            if duplicate:
                raise ValueError("服务对象名称已存在")

            conn.execute(
                """
                UPDATE service_users
                SET name=?, age=?, profile=?, allergies=?, note=?, status=?
                WHERE id=?
                """,
                (name, age, profile, allergies, note, status, user_id),
            )

        return ServiceUser(id=user_id, name=name, age=age, profile=profile, allergies=allergies, note=note, status=status)

    def delete_service_user(self, user_id: str) -> None:
        db.init_db()
        with db.connect() as conn:
            existing = conn.execute("SELECT id FROM service_users WHERE id=?", (user_id,)).fetchone()
            if not existing:
                raise ValueError("服务对象不存在")
            conn.execute("DELETE FROM service_users WHERE id=?", (user_id,))

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
