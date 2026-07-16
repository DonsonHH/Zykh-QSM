from __future__ import annotations

import json
import re
from datetime import date, timedelta
from uuid import uuid4

from .. import db
from ..repositories.device_action_repository import DeviceActionRepository
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.inquiry_repository import InquiryRepository
from ..repositories.vitals_repository import VitalsRepository
from ..schemas.dispense import DispenseRecord
from ..schemas.records import (
    RecentRecord,
    RecordsSummary,
    ServiceUser,
    ServiceUserCreateRequest,
    ServiceUserUpdateRequest,
    TodayPlan,
    TodayPlanCreateRequest,
    TodayPlanUpdateRequest,
)
from .sync_service import SyncService


class RecordsService:
    _plan_statuses = {"待执行", "已执行", "已跳过"}
    _schedule_types = {"daily", "interval", "weekly"}

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
            local_record_count=len(self._successful_dispense_records()),
            today_plan_count=len(self.list_today_plans(due_only=True)),
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
            conn.execute("DELETE FROM face_identities WHERE service_user_id=?", (user_id,))
            conn.execute("DELETE FROM fingerprint_identities WHERE service_user_id=?", (user_id,))
            conn.execute("DELETE FROM today_plans WHERE service_user_id=?", (user_id,))
            conn.execute("DELETE FROM service_users WHERE id=?", (user_id,))

    def list_today_plans(self, *, due_only: bool = False, reference_date: date | None = None) -> list[TodayPlan]:
        db.init_db()
        self._ensure_default_today_plan()
        current_date = reference_date or date.today()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.time, p.medicine_id, m.name AS medicine,
                       p.service_user_id, p.status, u.name AS target_user,
                       p.dose, p.updated_at, p.schedule_type, p.interval_days,
                       p.weekdays_json, p.start_date, p.last_action_date
                FROM today_plans AS p
                JOIN medicines AS m ON m.id=p.medicine_id
                JOIN service_users AS u ON u.id=p.service_user_id
                ORDER BY p.time, p.id
                """
            ).fetchall()
        plans = [self._plan_from_row(dict(row), current_date) for row in rows]
        return [plan for plan in plans if plan.due_today] if due_only else plans

    def create_today_plan(self, request: TodayPlanCreateRequest) -> TodayPlan:
        db.init_db()
        values = self._validated_plan_values(
            time_value=request.time,
            medicine_id=request.medicine_id,
            service_user_id=request.service_user_id,
            dose=request.dose,
            status=request.status,
            schedule_type=request.schedule_type,
            interval_days=request.interval_days,
            weekdays=request.weekdays,
            start_date=request.start_date,
        )
        plan_id = f"plan-{uuid4().hex[:14]}"
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO today_plans(
                  id, time, medicine_id, service_user_id, dose, status,
                  medicine, target_user, updated_at, schedule_type, interval_days,
                  weekdays_json, start_date, last_action_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    values["time"],
                    values["medicine_id"],
                    values["service_user_id"],
                    values["dose"],
                    values["status"],
                    values["medicine"],
                    values["target_user"],
                    db.now_text(),
                    values["schedule_type"],
                    values["interval_days"],
                    json.dumps(values["weekdays"]),
                    values["start_date"],
                    date.today().isoformat() if values["status"] in {"已执行", "已跳过"} else "",
                ),
            )
        return self.get_today_plan(plan_id)

    def update_today_plan(self, plan_id: str, request: TodayPlanUpdateRequest) -> TodayPlan:
        current = self.get_today_plan(plan_id)
        stored_status = current.status if current.status in self._plan_statuses else "待执行"
        values = self._validated_plan_values(
            time_value=request.time if request.time is not None else current.time,
            medicine_id=request.medicine_id if request.medicine_id is not None else current.medicine_id,
            service_user_id=request.service_user_id if request.service_user_id is not None else current.service_user_id,
            dose=request.dose if request.dose is not None else current.dose,
            status=request.status if request.status is not None else stored_status,
            schedule_type=request.schedule_type if request.schedule_type is not None else current.schedule_type,
            interval_days=request.interval_days if request.interval_days is not None else current.interval_days,
            weekdays=request.weekdays if request.weekdays is not None else current.weekdays,
            start_date=request.start_date if request.start_date is not None else current.start_date,
        )
        last_action_date = current.last_action_date
        if request.status is not None:
            last_action_date = date.today().isoformat() if values["status"] in {"已执行", "已跳过"} else ""
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE today_plans
                SET time=?, medicine_id=?, service_user_id=?, dose=?, status=?,
                    medicine=?, target_user=?, updated_at=?, schedule_type=?,
                    interval_days=?, weekdays_json=?, start_date=?, last_action_date=?
                WHERE id=?
                """,
                (
                    values["time"],
                    values["medicine_id"],
                    values["service_user_id"],
                    values["dose"],
                    values["status"],
                    values["medicine"],
                    values["target_user"],
                    db.now_text(),
                    values["schedule_type"],
                    values["interval_days"],
                    json.dumps(values["weekdays"]),
                    values["start_date"],
                    last_action_date,
                    plan_id,
                ),
            )
        return self.get_today_plan(plan_id)

    def delete_today_plan(self, plan_id: str) -> None:
        db.init_db()
        with db.connect() as conn:
            existing = conn.execute("SELECT id FROM today_plans WHERE id=?", (plan_id,)).fetchone()
            if not existing:
                raise ValueError("今日用药计划不存在")
            conn.execute("DELETE FROM today_plans WHERE id=?", (plan_id,))

    def get_today_plan(self, plan_id: str) -> TodayPlan:
        plans = {plan.id: plan for plan in self.list_today_plans()}
        if plan_id not in plans:
            raise ValueError("今日用药计划不存在")
        return plans[plan_id]

    def validate_dispense_plan(self, plan_id: str, medicine_id: str, service_user_id: str) -> TodayPlan:
        plan = self.get_today_plan(plan_id)
        if not plan.due_today:
            raise ValueError("该用药计划今天未到执行日期")
        if plan.status != "待执行":
            raise ValueError("该用药计划今天已经处理")
        if plan.medicine_id != medicine_id:
            raise ValueError("取药药品与用药计划不一致")
        if plan.service_user_id != service_user_id:
            raise ValueError(f"该计划属于{plan.target_user}，当前身份不能执行")
        return plan

    def complete_today_plan(self, plan_id: str, medicine_id: str, service_user_id: str) -> TodayPlan:
        self.validate_dispense_plan(plan_id, medicine_id, service_user_id)
        with db.connect() as conn:
            conn.execute(
                "UPDATE today_plans SET status='已执行', last_action_date=?, updated_at=? WHERE id=?",
                (date.today().isoformat(), db.now_text(), plan_id),
            )
        return self.get_today_plan(plan_id)

    def _validated_plan_values(
        self,
        *,
        time_value: str,
        medicine_id: str,
        service_user_id: str,
        dose: str,
        status: str,
        schedule_type: str,
        interval_days: int,
        weekdays: list[int],
        start_date: str,
    ) -> dict[str, object]:
        time_value = str(time_value or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value):
            raise ValueError("用药时间必须为 HH:MM")
        normalized_status = str(status or "").strip()
        if normalized_status not in self._plan_statuses:
            raise ValueError("计划状态不支持")
        normalized_dose = str(dose or "").strip()[:40] or "按说明"
        normalized_schedule = str(schedule_type or "daily").strip().lower()
        if normalized_schedule not in self._schedule_types:
            raise ValueError("计划周期不支持")
        normalized_interval = max(1, min(int(interval_days or 1), 30))
        normalized_weekdays = sorted({int(value) for value in (weekdays or []) if 1 <= int(value) <= 7})
        if normalized_schedule == "weekly" and not normalized_weekdays:
            raise ValueError("每周计划至少选择一天")
        normalized_start = str(start_date or date.today().isoformat()).strip()
        try:
            date.fromisoformat(normalized_start)
        except ValueError as exc:
            raise ValueError("计划起始日期必须为 YYYY-MM-DD") from exc
        with db.connect() as conn:
            medicine = conn.execute("SELECT id, name FROM medicines WHERE id=?", (medicine_id,)).fetchone()
            user = conn.execute("SELECT id, name FROM service_users WHERE id=?", (service_user_id,)).fetchone()
        if not medicine:
            raise ValueError("计划药品不存在")
        if not user:
            raise ValueError("计划服务对象不存在")
        return {
            "time": time_value,
            "medicine_id": str(medicine["id"]),
            "service_user_id": str(user["id"]),
            "dose": normalized_dose,
            "status": normalized_status,
            "medicine": str(medicine["name"]),
            "target_user": str(user["name"]),
            "schedule_type": normalized_schedule,
            "interval_days": normalized_interval,
            "weekdays": normalized_weekdays,
            "start_date": normalized_start,
        }

    @classmethod
    def _plan_from_row(cls, row: dict[str, object], current_date: date) -> TodayPlan:
        schedule_type = str(row.get("schedule_type") or "daily")
        interval_days = max(1, int(row.get("interval_days") or 1))
        try:
            weekdays = [int(value) for value in json.loads(str(row.get("weekdays_json") or "[]"))]
        except (TypeError, ValueError, json.JSONDecodeError):
            weekdays = []
        start_date = cls._parse_date(str(row.get("start_date") or ""), current_date)
        due_today = cls._is_due(current_date, start_date, schedule_type, interval_days, weekdays)
        last_action_date = str(row.get("last_action_date") or "")
        stored_status = str(row.get("status") or "待执行")
        status = stored_status if due_today and last_action_date == current_date.isoformat() else "待执行"
        if not due_today:
            status = "未到期"
        next_due = cls._next_due_date(current_date, start_date, schedule_type, interval_days, weekdays)
        return TodayPlan(
            id=str(row["id"]),
            time=str(row["time"]),
            medicine_id=str(row["medicine_id"]),
            medicine=str(row["medicine"]),
            service_user_id=str(row["service_user_id"]),
            status=status,
            target_user=str(row["target_user"]),
            dose=str(row.get("dose") or "按说明"),
            updated_at=str(row.get("updated_at") or ""),
            schedule_type=schedule_type,
            interval_days=interval_days,
            weekdays=weekdays,
            start_date=start_date.isoformat(),
            last_action_date=last_action_date,
            due_today=due_today,
            next_due_date=next_due.isoformat(),
            frequency_label=cls._frequency_label(schedule_type, interval_days, weekdays),
        )

    @staticmethod
    def _parse_date(value: str, fallback: date) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return fallback

    @staticmethod
    def _is_due(current: date, start: date, schedule_type: str, interval_days: int, weekdays: list[int]) -> bool:
        if current < start:
            return False
        if schedule_type == "weekly":
            return current.isoweekday() in weekdays
        if schedule_type == "interval":
            return (current - start).days % max(1, interval_days) == 0
        return True

    @classmethod
    def _next_due_date(cls, current: date, start: date, schedule_type: str, interval_days: int, weekdays: list[int]) -> date:
        candidate = max(current, start)
        for offset in range(367):
            day = candidate + timedelta(days=offset)
            if cls._is_due(day, start, schedule_type, interval_days, weekdays):
                return day
        return candidate

    @staticmethod
    def _frequency_label(schedule_type: str, interval_days: int, weekdays: list[int]) -> str:
        if schedule_type == "interval":
            return f"每 {interval_days} 天"
        if schedule_type == "weekly":
            labels = ["一", "二", "三", "四", "五", "六", "日"]
            return "每周" + "、".join(labels[value - 1] for value in weekdays if 1 <= value <= 7)
        return "每天"

    @staticmethod
    def _ensure_default_today_plan() -> None:
        from .medicine_service import MedicineService

        MedicineService().list_medicines()
        with db.connect() as conn:
            seed = conn.execute("SELECT value FROM app_settings WHERE key='today_plan_seed_version'").fetchone()
            if seed and seed["value"] == "normalized-v1":
                return
            if conn.execute("SELECT COUNT(*) AS count FROM today_plans").fetchone()["count"] == 0:
                user = conn.execute("SELECT id, name FROM service_users WHERE name='张三' LIMIT 1").fetchone()
                medicine = conn.execute(
                    "SELECT id, name FROM medicines WHERE id='slot-21-amlodipine' LIMIT 1"
                ).fetchone()
                if user and medicine:
                    conn.execute(
                        """
                        INSERT INTO today_plans(
                          id, time, medicine_id, service_user_id, dose, status,
                          medicine, target_user, updated_at, schedule_type,
                          interval_days, weekdays_json, start_date, last_action_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "plan-zhangsan-amlodipine",
                            "08:00",
                            medicine["id"],
                            user["id"],
                            "1片",
                            "待执行",
                            medicine["name"],
                            user["name"],
                            db.now_text(),
                            "daily",
                            1,
                            "[]",
                            date.today().isoformat(),
                            "",
                        ),
                    )
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at) VALUES ('today_plan_seed_version', 'normalized-v1', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (db.now_text(),),
            )

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
                title=f"{self._dispense_actor(record.target_user_name, record.target_user_type)}取走{record.medicine_name}",
                description=f"{record.quantity}{record.unit}",
                target_user=record.target_user_name,
                status="已记录",
                sync_status=sync_status,
                target_user_type=record.target_user_type,
            )
            for record in self._successful_dispense_records()
        ]

    def _successful_dispense_records(self) -> list[DispenseRecord]:
        return [
            record
            for record in self.dispense_repository.list_records()
            if record.qsm_ok and not record.dry_run
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

    @staticmethod
    def _dispense_actor(name: str, user_type: str) -> str:
        normalized = str(name or "").strip()
        if user_type == "guest":
            if normalized and not normalized.startswith("游客"):
                return f"游客（{normalized}）"
            return normalized or "游客"
        return normalized or "家庭成员"
