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
from ..schemas.inquiry import InquirySessionResponse
from ..schemas.records import (
    RecentRecord,
    RecordsSummary,
    ServiceUser,
    ServiceUserCreateRequest,
    ServiceUserInquiryHistoryItem,
    ServiceUserInquiryHistoryResponse,
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
        return records[:20]

    def list_service_users(self) -> list[ServiceUser]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, age, profile, allergies, note, status,
                       medical_conditions_json, current_medications_json,
                       allergy_facts_json, safety_profile_revision,
                       safety_profile_updated_at, persona_generation, archived
                FROM service_users
                WHERE archived=0
                ORDER BY id
                """
            ).fetchall()
        return [self._service_user_from_row(row) for row in rows]

    def list_service_user_inquiries(
        self,
        user_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ServiceUserInquiryHistoryResponse:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("服务对象不存在")
        if not 1 <= int(limit) <= 20:
            raise ValueError("历史问询分页数量必须在 1 到 20 之间")
        db.init_db()
        with db.connect() as conn:
            exists = conn.execute(
                "SELECT id FROM service_users WHERE id=?",
                (normalized_user_id,),
            ).fetchone()
        if not exists:
            raise ValueError("服务对象不存在")

        normalized_cursor = str(cursor or "").strip()
        selected, next_cursor = self.inquiry_repository.list_user_sessions_page(
            normalized_user_id,
            limit=limit,
            cursor=normalized_cursor,
        )
        return ServiceUserInquiryHistoryResponse(
            user_id=normalized_user_id,
            inquiries=[self._service_user_inquiry_item(session) for session in selected],
            next_cursor=next_cursor,
        )

    @staticmethod
    def _service_user_inquiry_item(
        session: InquirySessionResponse,
    ) -> ServiceUserInquiryHistoryItem:
        extracted = session.extracted_information
        case_summary = (
            extracted.case_summary.strip()
            or extracted.symptoms_text.strip()
            or "未形成病例摘要"
        )
        risk_level = session.risk_level or ""
        risk_label = {
            "low": "低风险",
            "medium": "中风险",
            "high": "高风险",
            "emergency": "紧急风险",
        }.get(risk_level, "未分级")
        if session.action_status == "complete":
            outcome = "已完成用户确认的取药流程"
        elif session.can_view_medicines:
            outcome = "已展示候选药品信息"
        elif risk_level in {"high", "emergency"}:
            outcome = "已建议联系医生或现场协助人员"
        else:
            outcome = "问询已记录"
        return ServiceUserInquiryHistoryItem(
            session_id=session.session_id,
            happened_at=session.updated_at,
            title=session.title,
            case_summary=case_summary[:240],
            risk_level=risk_level,
            risk_label=risk_label,
            outcome=outcome,
            final_medicine_summary=RecordsService._final_medicine_summary(session),
        )

    @staticmethod
    def _final_medicine_summary(session: InquirySessionResponse) -> str:
        names = [
            str(item.get("medicine_name") or item.get("name") or "").strip()
            for item in session.action_items
            if isinstance(item, dict) and item.get("ok") is not False
        ]
        if not any(names) and session.selected_option_id:
            selected = next(
                (
                    option
                    for option in session.treatment_options
                    if option.option_id == session.selected_option_id
                ),
                None,
            )
            if selected is not None:
                names = [medicine.name.strip() for medicine in selected.medicines]
        unique_names = list(dict.fromkeys(name for name in names if name))
        return "、".join(unique_names)[:160]

    def create_service_user(self, request: ServiceUserCreateRequest) -> ServiceUser:
        db.init_db()
        name = request.name.strip()[:12] or "新使用人"
        age = max(0, min(int(request.age or 0), 120))
        profile = request.profile.strip()[:80] or "待补充"
        allergies = request.allergies.strip()[:80]
        note = request.note.strip()[:120] or "AI问询新建"
        status = request.status.strip()[:20] or "待完善"
        medical_conditions = list(request.medical_conditions)
        current_medications = list(request.current_medications)
        allergy_facts = list(request.allergy_facts)
        persona_generation = request.persona_generation.strip()[:80]
        safety_updated_at = db.now_text()
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", name) or "user"
        user_id = f"user-{slug}-{db.now_text().replace(' ', '-').replace(':', '')}"
        with db.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, name, age, profile, allergies, note, status,
                       medical_conditions_json, current_medications_json,
                       allergy_facts_json, safety_profile_revision,
                       safety_profile_updated_at, persona_generation, archived
                FROM service_users WHERE name=? AND archived=0
                """,
                (name,),
            ).fetchone()
            if existing:
                return self._service_user_from_row(existing)
            conn.execute(
                """
                INSERT INTO service_users(
                  id, name, age, profile, allergies, note, status,
                  medical_conditions_json, current_medications_json,
                  allergy_facts_json, safety_profile_revision,
                  safety_profile_updated_at, persona_generation, archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 0)
                """,
                (
                    user_id, name, age, profile, allergies, note, status,
                    json.dumps(medical_conditions, ensure_ascii=False),
                    json.dumps(current_medications, ensure_ascii=False),
                    json.dumps(allergy_facts, ensure_ascii=False),
                    safety_updated_at,
                    persona_generation,
                ),
            )
        return ServiceUser(
            id=user_id,
            name=name,
            age=age,
            profile=profile,
            allergies=allergies,
            note=note,
            status=status,
            medical_conditions=medical_conditions,
            current_medications=current_medications,
            allergy_facts=allergy_facts,
            safety_profile_revision=1,
            safety_profile_updated_at=safety_updated_at,
            persona_generation=persona_generation,
        )

    def update_service_user(self, user_id: str, request: ServiceUserUpdateRequest) -> ServiceUser:
        db.init_db()
        with db.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, name, age, profile, allergies, note, status,
                       medical_conditions_json, current_medications_json,
                       allergy_facts_json, safety_profile_revision,
                       safety_profile_updated_at, persona_generation, archived
                FROM service_users WHERE id=?
                """,
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
            medical_conditions = (
                list(request.medical_conditions)
                if request.medical_conditions is not None
                else self._json_list(current["medical_conditions_json"])
            )
            current_medications = (
                list(request.current_medications)
                if request.current_medications is not None
                else self._json_list(current["current_medications_json"])
            )
            allergy_facts = (
                list(request.allergy_facts)
                if request.allergy_facts is not None
                else self._json_list(current["allergy_facts_json"])
            )
            persona_generation = (
                request.persona_generation
                if request.persona_generation is not None
                else current["persona_generation"]
            ).strip()[:80]
            archived = bool(request.archived) if request.archived is not None else bool(current["archived"])
            safety_changed = any(
                (
                    profile != current["profile"],
                    allergies != current["allergies"],
                    medical_conditions != self._json_list(current["medical_conditions_json"]),
                    current_medications != self._json_list(current["current_medications_json"]),
                    allergy_facts != self._json_list(current["allergy_facts_json"]),
                    persona_generation != current["persona_generation"],
                )
            )
            safety_profile_revision = int(current["safety_profile_revision"] or 1) + (1 if safety_changed else 0)
            safety_profile_updated_at = db.now_text() if safety_changed else str(current["safety_profile_updated_at"] or "")

            duplicate = conn.execute(
                "SELECT id FROM service_users WHERE name=? AND id<>?",
                (name, user_id),
            ).fetchone()
            if duplicate:
                raise ValueError("服务对象名称已存在")

            conn.execute(
                """
                UPDATE service_users
                SET name=?, age=?, profile=?, allergies=?, note=?, status=?,
                    medical_conditions_json=?, current_medications_json=?,
                    allergy_facts_json=?, safety_profile_revision=?,
                    safety_profile_updated_at=?, persona_generation=?, archived=?
                WHERE id=?
                """,
                (
                    name, age, profile, allergies, note, status,
                    json.dumps(medical_conditions, ensure_ascii=False),
                    json.dumps(current_medications, ensure_ascii=False),
                    json.dumps(allergy_facts, ensure_ascii=False),
                    safety_profile_revision,
                    safety_profile_updated_at,
                    persona_generation,
                    int(archived),
                    user_id,
                ),
            )

        return ServiceUser(
            id=user_id,
            name=name,
            age=age,
            profile=profile,
            allergies=allergies,
            note=note,
            status=status,
            medical_conditions=medical_conditions,
            current_medications=current_medications,
            allergy_facts=allergy_facts,
            safety_profile_revision=safety_profile_revision,
            safety_profile_updated_at=safety_profile_updated_at,
            persona_generation=persona_generation,
            archived=archived,
        )

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
                SELECT p.id, p.time, p.timing_label, p.medicine_id, m.name AS medicine,
                       p.service_user_id, p.status, u.name AS target_user,
                       p.dose, p.updated_at, p.schedule_type, p.interval_days,
                       p.weekdays_json, p.start_date, p.last_action_date
                FROM today_plans AS p
                JOIN medicines AS m ON m.id=p.medicine_id
                JOIN service_users AS u ON u.id=p.service_user_id
                WHERE p.archived=0 AND u.archived=0
                ORDER BY p.time, p.id
                """
            ).fetchall()
        plans = [self._plan_from_row(dict(row), current_date) for row in rows]
        return [plan for plan in plans if plan.due_today] if due_only else plans

    def create_today_plan(self, request: TodayPlanCreateRequest) -> TodayPlan:
        db.init_db()
        values = self._validated_plan_values(
            time_value=request.time,
            timing_label=request.timing_label,
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
                  id, time, timing_label, medicine_id, service_user_id, dose, status,
                  medicine, target_user, updated_at, schedule_type, interval_days,
                  weekdays_json, start_date, last_action_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    values["time"],
                    values["timing_label"],
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
            timing_label=request.timing_label if request.timing_label is not None else current.timing_label,
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
                SET time=?, timing_label=?, medicine_id=?, service_user_id=?, dose=?, status=?,
                    medicine=?, target_user=?, updated_at=?, schedule_type=?,
                    interval_days=?, weekdays_json=?, start_date=?, last_action_date=?
                WHERE id=?
                """,
                (
                    values["time"],
                    values["timing_label"],
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
        timing_label: str,
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
        normalized_timing_label = str(timing_label or "").strip()[:12]
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
            user = conn.execute(
                "SELECT id, name FROM service_users WHERE id=? AND archived=0",
                (service_user_id,),
            ).fetchone()
        if not medicine:
            raise ValueError("计划药品不存在")
        if not user:
            raise ValueError("计划服务对象不存在")
        return {
            "time": time_value,
            "timing_label": normalized_timing_label,
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
            timing_label=str(row.get("timing_label") or ""),
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
    def _json_list(value: object) -> list[dict[str, object]]:
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []

    @classmethod
    def _service_user_from_row(cls, row: object) -> ServiceUser:
        values = dict(row)
        return ServiceUser(
            id=str(values["id"]),
            name=str(values["name"]),
            age=int(values["age"] or 0),
            profile=str(values["profile"] or ""),
            allergies=str(values["allergies"] or ""),
            note=str(values["note"] or ""),
            status=str(values["status"] or ""),
            medical_conditions=cls._json_list(values.get("medical_conditions_json")),
            current_medications=cls._json_list(values.get("current_medications_json")),
            allergy_facts=cls._json_list(values.get("allergy_facts_json")),
            safety_profile_revision=max(1, int(values.get("safety_profile_revision") or 1)),
            safety_profile_updated_at=str(values.get("safety_profile_updated_at") or ""),
            persona_generation=str(values.get("persona_generation") or ""),
            archived=bool(values.get("archived")),
        )

    @staticmethod
    def _ensure_default_today_plan() -> None:
        from .medicine_service import MedicineService

        MedicineService().list_medicines()
        seed_version = "family-demo-v7-senior-safety"
        demo_plans = (
            ("plan-demo-wang-amlodipine", "08:00", "早餐后", "slot-21-amlodipine", "wang-nainai", "1 片（按既往有效医嘱）"),
            ("plan-demo-wang-budesonide", "21:00", "睡前", "slot-18-budesonide-nasal", "wang-nainai", "每侧鼻孔 1 喷（按既往有效医嘱）"),
            ("plan-demo-li-lactulose", "07:30", "早餐时", "slot-06-lactulose", "li-yeye", "10 毫升（按既往有效医嘱）"),
            ("plan-demo-li-desloratadine", "20:30", "睡前", "slot-23-desloratadine", "li-yeye", "每次 1 粒（按既往有效医嘱）"),
        )
        with db.connect() as conn:
            seed = conn.execute("SELECT value FROM app_settings WHERE key='today_plan_seed_version'").fetchone()
            if seed and seed["value"] == seed_version:
                return
            users = {
                str(row["id"]): row
                for row in conn.execute(
                    "SELECT id, name FROM service_users WHERE id IN ('wang-nainai', 'li-yeye') AND archived=0"
                ).fetchall()
            }
            if set(users) != {"wang-nainai", "li-yeye"}:
                return
            if not db.has_exact_senior_demo_personas(conn):
                return
            conn.execute(
                """
                DELETE FROM today_plans
                WHERE id LIKE 'plan-demo-zhangsan-%'
                   OR id LIKE 'plan-demo-lisi-%'
                """
            )
            for plan_id, time_value, timing_label, medicine_id, user_id, dose in demo_plans:
                user = users.get(user_id)
                medicine = conn.execute(
                    "SELECT id, name FROM medicines WHERE id=? LIMIT 1",
                    (medicine_id,),
                ).fetchone()
                if not user or not medicine:
                    continue
                conn.execute(
                    """
                    INSERT INTO today_plans(
                      id, time, timing_label, medicine_id, service_user_id, dose, status,
                      medicine, target_user, updated_at, schedule_type,
                      interval_days, weekdays_json, start_date, last_action_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        plan_id,
                        time_value,
                        timing_label,
                        medicine["id"],
                        user["id"],
                        dose,
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
                INSERT INTO app_settings(key, value, updated_at) VALUES ('today_plan_seed_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (seed_version, db.now_text()),
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
        records = self._successful_dispense_records()
        user_ids = {record.target_user_id for record in records if record.target_user_id}
        user_names: dict[str, str] = {}
        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            with db.connect() as conn:
                rows = conn.execute(
                    f"SELECT id, name FROM service_users WHERE id IN ({placeholders})",
                    tuple(user_ids),
                ).fetchall()
            user_names = {str(row["id"]): str(row["name"]) for row in rows}

        recent: list[RecentRecord] = []
        for record in records:
            stored_name = str(record.target_user_name or "").strip()
            display_name = user_names.get(record.target_user_id) or stored_name
            if not display_name or display_name == "家庭成员":
                display_name = "游客"
            user_type = record.target_user_type
            if display_name == "游客" and not record.target_user_id:
                user_type = "guest"
            recent.append(
                RecentRecord(
                    id=record.id,
                    time=self._history_time(record.created_at),
                    type="取药记录",
                    title=record.medicine_name,
                    description=f"{record.quantity}{record.unit}",
                    target_user=display_name,
                    status="已记录",
                    sync_status=sync_status,
                    target_user_type=user_type,
                )
            )
        return recent

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
    def _history_time(value: str) -> str:
        normalized = str(value or "").replace("T", " ")
        match = re.match(r"\d{4}-(\d{2}-\d{2})\s+(\d{2}:\d{2})", normalized)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return normalized[:16] or "时间未记录"
