from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .. import db
from ..config import settings
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.inquiry_repository import InquiryRepository
from ..repositories.medicine_repository import MedicineRepository
from ..repositories.sync_repository import SyncRepository
from ..schemas.dispense import DispenseOpenRequest
from ..schemas.medicine import MedicineUpdateRequest
from ..schemas.records import (
    ServiceUserCreateRequest,
    ServiceUserUpdateRequest,
    TodayPlanCreateRequest,
    TodayPlanUpdateRequest,
)
from ..schemas.sync import SyncStatus
from .ai_service import AiService
from .dispense_service import DispenseService
from .qsm_client import QsmClient
from .host_offline_tts import get_host_offline_tts


class CloudSyncError(RuntimeError):
    pass


class CloudSyncWorker:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._last_snapshot_hash = ""
        self._cloud_schema_version: int | None = None
        self._cloud_schema_revision = ""
        self._cloud_schema_checked_at = 0.0
        self._connected = False
        self._last_error = ""
        self._last_command_at = ""

    def start(self) -> None:
        if not settings.cloud_sync_enabled or not settings.cloud_sync_endpoint.strip():
            return
        if self._thread and self._thread.is_alive():
            return
        self._recover_interrupted_commands()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="zykh-cloud-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(2.0, settings.cloud_sync_timeout_seconds + 1))
        self._thread = None

    def runtime_status(self, base: SyncStatus) -> SyncStatus:
        with self._state_lock:
            return base.model_copy(
                update={
                    "connected": self._connected,
                    "device_id": settings.cloud_sync_device_id,
                    "last_error": self._last_error,
                    "last_command_at": self._last_command_at,
                    "interval_seconds": settings.cloud_sync_interval_seconds,
                }
            )

    def run_once(self) -> tuple[int, str]:
        if not settings.cloud_sync_enabled:
            raise CloudSyncError("云同步已关闭。")
        if not self._run_lock.acquire(blocking=False):
            return 0, "同步正在进行。"
        try:
            self._flush_unacked_commands()
            commands = self._call("PULL_COMMANDS", {"limit": 10, "agentVersion": 2})
            if not isinstance(commands, list):
                commands = commands.get("commands", []) if isinstance(commands, dict) else []
            for command in commands:
                self._handle_command(command)

            snapshot = self._build_snapshot()
            from .network_service import NetworkService

            network_status = NetworkService().status()
            self._call(
                "REPORT_DEVICE",
                {
                    "online": True,
                    "network": str(network_status.get("transport") or network_status.get("mode") or "local"),
                    "signal": str(network_status.get("signal") or "none"),
                    "cloudAgent": "zykh_station_app",
                    "localApi": "http://127.0.0.1:8000",
                    "board": "智药康护终端",
                    "schemaVersion": 2,
                    "syncSummary": self._sync_summary(snapshot),
                },
            )

            encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            schema_version = self._detect_schema_version()
            snapshot_hash = hashlib.sha256(
                f"{schema_version}:{self._cloud_schema_revision}:{encoded}".encode("utf-8")
            ).hexdigest()
            synced_count = 0
            if not self._last_snapshot_hash:
                self._last_snapshot_hash = db.get_setting("cloud_snapshot_hash", "")
            if snapshot_hash != self._last_snapshot_hash:
                synced_count = self._sync_snapshot(snapshot)
                self._last_snapshot_hash = snapshot_hash
                db.set_setting("cloud_snapshot_hash", snapshot_hash)

            now = db.now_text()
            current = SyncRepository().get_status()
            SyncRepository().save_status(
                SyncStatus(
                    sync_status="已同步",
                    pending_count=0,
                    last_sync_at=now,
                    network_mode=current.network_mode or "家庭网络",
                    connected=True,
                    device_id=settings.cloud_sync_device_id,
                    last_error="",
                    last_command_at=self._last_command_at,
                    interval_seconds=settings.cloud_sync_interval_seconds,
                )
            )
            with self._state_lock:
                self._connected = True
                self._last_error = ""
            return synced_count, f"云端同步完成，处理 {len(commands)} 条命令。"
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            current = SyncRepository().get_status()
            SyncRepository().save_status(
                SyncStatus(
                    sync_status="待同步",
                    pending_count=max(1, current.pending_count),
                    last_sync_at=current.last_sync_at,
                    network_mode=current.network_mode,
                )
            )
            with self._state_lock:
                self._connected = False
                self._last_error = message
            raise CloudSyncError(message) from exc
        finally:
            self._run_lock.release()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except CloudSyncError:
                pass
            self._stop_event.wait(max(1.0, settings.cloud_sync_interval_seconds))

    def _call(self, action: str, data: dict[str, object]) -> Any:
        payload_data = dict(data)
        payload_data["deviceId"] = settings.cloud_sync_device_id
        secret = self._device_secret()
        if secret:
            payload_data["deviceSecret"] = secret
        body = json.dumps({"action": action, "data": payload_data}, ensure_ascii=False).encode("utf-8")
        request = Request(
            settings.cloud_sync_endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=settings.cloud_sync_timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raise CloudSyncError(f"云端接口 HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise CloudSyncError(f"云端接口暂不可用：{exc}") from exc
        try:
            result: Any = json.loads(raw)
            if isinstance(result, dict) and "body" in result and isinstance(result["body"], str):
                result = json.loads(result["body"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise CloudSyncError("云端接口返回了无效数据。") from exc
        if isinstance(result, dict) and result.get("ok") is False:
            raise CloudSyncError(str(result.get("error") or "云端接口拒绝请求。"))
        return result

    @staticmethod
    def _device_secret() -> str:
        if settings.cloud_sync_device_secret.strip():
            return settings.cloud_sync_device_secret.strip()
        path: Path = settings.cloud_sync_device_secret_file
        try:
            return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        except OSError:
            return ""

    @staticmethod
    def _build_snapshot() -> dict[str, list[dict[str, object]]]:
        from .records_service import RecordsService

        medicines = []
        for medicine in MedicineRepository().list_all():
            row = medicine.model_dump(mode="json")
            row.update(
                {
                    "slot": medicine.hardware_slot,
                    "spec": medicine.category,
                    "quantity": medicine.stock,
                    "expireDate": medicine.expire_date,
                    "lowStockLine": 1,
                }
            )
            medicines.append(row)

        records_service = RecordsService()
        service_users = [item.model_dump(mode="json") for item in records_service.list_service_users()]
        plans = [item.model_dump(mode="json") for item in records_service.list_today_plans(due_only=False)]
        inquiry_repository = InquiryRepository()
        inquiries: list[dict[str, object]] = []
        inquiry_ids: set[str] = set()
        for session in inquiry_repository.list_sessions(limit=100):
            row = session.model_dump(mode="json")
            row.update(
                {
                    "inquiry_id": session.session_id,
                    "target_user_id": session.user_id,
                    "target_user_name": session.user_name,
                    "symptoms_summary": session.extracted_information.symptoms_text or session.title,
                    "createdAt": session.created_at,
                    "updatedAt": session.updated_at,
                }
            )
            inquiries.append(row)
            inquiry_ids.add(session.session_id)
        for result in inquiry_repository.list_records():
            if result.inquiry_id in inquiry_ids:
                continue
            row = result.model_dump(mode="json")
            row.update({"createdAt": result.created_at, "updatedAt": result.created_at})
            inquiries.append(row)
        records = []
        for item in DispenseRepository().list_records():
            row = item.model_dump(mode="json")
            row.update(
                {
                    "type": "DISPENSE",
                    "message": f"{CloudSyncWorker._cloud_record_actor(item.target_user_name, item.target_user_type)}于{item.created_at}取用{item.medicine_name}",
                    "createdAt": item.created_at,
                }
            )
            records.append(row)

        db.init_db()
        with db.connect() as conn:
            vitals_rows = conn.execute(
                """
                SELECT id, temperature, heart_rate, spo2, systolic_pressure, diastolic_pressure,
                       respiratory_rate, microcirculation, fatigue, rr_interval, hrv_sdnn, hrv_rmssd,
                       body_temperature, ambient_temperature, status, source, sensor_model,
                       error_message, measured_at
                FROM vitals_records ORDER BY measured_at DESC LIMIT 100
                """
            ).fetchall()
        vitals = []
        for raw in vitals_rows:
            row = dict(raw)
            row.update(
                {
                    "heartRate": row["heart_rate"],
                    "bodyTemp": row["temperature"],
                    "quality": row["status"],
                    "createdAt": row["measured_at"],
                }
            )
            vitals.append(row)
        return {
            "medicines": medicines,
            "serviceUsers": service_users,
            "plans": plans,
            "inquiries": inquiries,
            "vitals": vitals,
            "records": records,
        }

    @staticmethod
    def _cloud_record_actor(name: str, user_type: str) -> str:
        if user_type == "guest":
            return name if str(name).startswith("游客") else f"游客（{name or '未登记'}）"
        return name or "家庭成员"

    def _sync_snapshot(self, snapshot: dict[str, list[dict[str, object]]]) -> int:
        if self._cloud_schema_version < 2:
            return self._sync_snapshot_v1(snapshot)

        synced = 0
        for key in ("medicines", "serviceUsers", "plans", "inquiries", "vitals", "records"):
            ids: list[str] = []
            for rows in self._snapshot_batches(snapshot.get(key, [])):
                result = self._call("UPSERT_SNAPSHOT_BATCH", {"kind": key, "rows": rows})
                if isinstance(result, dict):
                    ids.extend(str(value) for value in result.get("ids", []))
                    synced += int(result.get("count") or 0)
            self._call("FINALIZE_SNAPSHOT", {"kind": key, "ids": ids})
        return synced

    @staticmethod
    def _snapshot_batches(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
        batches: list[list[dict[str, object]]] = []
        current: list[dict[str, object]] = []
        current_size = 0
        for row in rows:
            size = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if current and (len(current) >= 20 or current_size + size > 48_000):
                batches.append(current)
                current = []
                current_size = 0
            current.append(row)
            current_size += size
        if current:
            batches.append(current)
        return batches

    def _detect_schema_version(self) -> int:
        now = time.monotonic()
        if self._cloud_schema_version is None or now - self._cloud_schema_checked_at >= 30:
            ping = self._call("PING", {})
            self._cloud_schema_version = int(ping.get("schemaVersion") or 1) if isinstance(ping, dict) else 1
            self._cloud_schema_revision = str(ping.get("schemaRevision") or "") if isinstance(ping, dict) else ""
            self._cloud_schema_checked_at = now
        return self._cloud_schema_version

    def _sync_snapshot_v1(self, snapshot: dict[str, list[dict[str, object]]]) -> int:
        synced = 0
        self._call("UPLOAD_MEDICINES", {"medicines": snapshot.get("medicines", [])})
        synced += len(snapshot.get("medicines", []))

        for vital in snapshot.get("vitals", [])[:10]:
            synced += self._upload_legacy_item("vitals", vital, "UPLOAD_VITALS", {"vitals": vital})

        record_groups = (
            ("dispense", snapshot.get("records", [])[:10]),
        )
        for kind, rows in record_groups:
            for row in rows:
                row_id = str(row.get("id") or row.get("inquiry_id") or "")
                record = dict(row)
                record.setdefault("id", row_id)
                record.setdefault("type", kind.upper().replace("-", "_"))
                record.setdefault("message", self._legacy_record_message(kind, row))
                record.setdefault("createdAt", row.get("created_at") or row.get("updated_at") or db.now_text())
                synced += self._upload_legacy_item(kind, record, "UPLOAD_RECORD", {"record": record})
        return synced

    @staticmethod
    def _sync_summary(snapshot: dict[str, list[dict[str, object]]]) -> dict[str, object]:
        inquiries = snapshot.get("inquiries", [])[:10]
        return {
            "counts": {key: len(value) for key, value in snapshot.items()},
            "serviceUsers": snapshot.get("serviceUsers", []),
            "plans": snapshot.get("plans", []),
            "recentInquiries": [
                {
                    "inquiry_id": row.get("inquiry_id") or row.get("session_id"),
                    "session_id": row.get("session_id") or row.get("inquiry_id"),
                    "target_user_id": row.get("target_user_id") or row.get("user_id"),
                    "target_user_name": row.get("target_user_name") or row.get("user_name"),
                    "title": row.get("title"),
                    "risk_level": row.get("risk_level"),
                    "risk_label": row.get("risk_label"),
                    "symptoms_summary": row.get("symptoms_summary"),
                    "reply": row.get("reply") or row.get("ai_message"),
                    "messages": row.get("messages") or [],
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at") or row.get("created_at"),
                }
                for row in inquiries
            ],
        }

    def _upload_legacy_item(
        self,
        kind: str,
        row: dict[str, object],
        action: str,
        payload: dict[str, object],
    ) -> int:
        row_id = str(row.get("id") or row.get("inquiry_id") or row.get("measured_at") or "").strip()
        if not row_id:
            return 0
        content = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        marker = f"cloud_v1_{kind}_{row_id}"
        if db.get_setting(marker, "") == content_hash:
            return 0
        self._call(action, payload)
        db.set_setting(marker, content_hash)
        return 1

    @staticmethod
    def _legacy_record_message(kind: str, row: dict[str, object]) -> str:
        if kind == "service-user":
            return f"服务对象：{row.get('name') or '未命名'}，{row.get('age') or '--'}岁，{row.get('profile') or '资料待补充'}"
        if kind == "today-plan":
            return f"今日计划：{row.get('target_user') or ''} {row.get('time') or ''} {row.get('medicine') or ''}"
        if kind == "inquiry":
            return f"问询记录：{row.get('symptoms_summary') or row.get('risk_label') or ''}"
        return str(row.get("message") or "本地服务记录")

    def _handle_command(self, command: dict[str, object]) -> None:
        command_id = str(command.get("_id") or command.get("id") or "").strip()
        command_type = str(command.get("type") or "").strip()
        if not command_id:
            return
        existing = self._command_history(command_id)
        if existing and existing["status"] in {"done", "done_unacked", "failed", "failed_unacked"}:
            final_status = "done" if str(existing["status"]).startswith("done") else "failed"
            result = json.loads(existing["result_json"] or "{}")
            self._ack(command_id, final_status, result)
            self._save_command(command_id, command_type, final_status, result, str(existing["created_at"] or db.now_text()))
            return
        now = db.now_text()
        self._save_command(command_id, command_type, "running", {}, now)
        try:
            result = self._execute_command(command_type, command)
        except Exception as exc:
            result = {"error": str(exc) or exc.__class__.__name__}
            self._save_command(command_id, command_type, "failed_unacked", result, now)
            try:
                self._ack(command_id, "failed", result)
            except CloudSyncError:
                raise
            self._save_command(command_id, command_type, "failed", result, now)
            return

        self._save_command(command_id, command_type, "done_unacked", result, now)
        try:
            self._ack(command_id, "done", result)
        except CloudSyncError:
            raise
        self._save_command(command_id, command_type, "done", result, now)
        with self._state_lock:
            self._last_command_at = db.now_text()
        self._last_snapshot_hash = ""

    def _flush_unacked_commands(self) -> None:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT command_id, command_type, status, result_json, created_at
                FROM cloud_command_history
                WHERE status IN ('done_unacked', 'failed_unacked')
                ORDER BY created_at ASC
                """
            ).fetchall()
        for row in rows:
            final_status = "done" if str(row["status"]).startswith("done") else "failed"
            result = json.loads(row["result_json"] or "{}")
            self._ack(str(row["command_id"]), final_status, result)
            self._save_command(
                str(row["command_id"]),
                str(row["command_type"]),
                final_status,
                result,
                str(row["created_at"]),
            )

    @staticmethod
    def _recover_interrupted_commands() -> None:
        db.init_db()
        message = {"error": "终端在命令执行期间重启，结果未知；为防止重复开柜，已禁止自动重试。"}
        with db.connect() as conn:
            conn.execute(
                """
                UPDATE cloud_command_history
                SET status='failed_unacked', result_json=?, updated_at=?
                WHERE status='running'
                """,
                (json.dumps(message, ensure_ascii=False), db.now_text()),
            )

    def _execute_command(self, command_type: str, command: dict[str, object]) -> dict[str, object]:
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        if command_type == "AUDIO_BEEP":
            return QsmClient().audio_beep(self._int(payload.get("volume")))
        if command_type == "AUDIO_SPEAK":
            return self._speak_reminder(payload)
        if command_type == "READ_VITALS_ALL":
            from ..routers.qsm import qsm_vitals

            return qsm_vitals(full=True).model_dump(mode="json")
        if command_type == "AI_CHAT":
            question = str(payload.get("question") or payload.get("message") or "").strip()
            if not question:
                raise CloudSyncError("AI_CHAT 缺少问题内容。")
            return AiService().chat(question)
        if command_type == "UPSERT_MEDICINE":
            return self._upsert_medicine(payload)
        if command_type == "UPSERT_SERVICE_USER":
            return self._upsert_service_user(payload)
        if command_type == "UPSERT_TODAY_PLAN":
            return self._upsert_today_plan(payload)
        if command_type == "OPEN_CABINET":
            return self._open_cabinet(payload, command)
        raise CloudSyncError(f"不支持的云端命令：{command_type}")

    @staticmethod
    def _speak_reminder(payload: dict[str, object]) -> dict[str, object]:
        text = str(payload.get("text") or payload.get("message") or "").strip()
        if not text:
            user_name = str(
                payload.get("target_user_name")
                or payload.get("user_name")
                or payload.get("targetUserName")
                or payload.get("patient_name")
                or payload.get("name")
                or ""
            ).strip()
            medicine_name = str(
                payload.get("medicine_name")
                or payload.get("medicineName")
                or payload.get("medicine")
                or ""
            ).strip()
            if user_name and medicine_name:
                text = f"{user_name}，该服用{medicine_name}了。"
            elif user_name:
                text = f"{user_name}，该服药了。"
        if not text:
            raise CloudSyncError("AUDIO_SPEAK 缺少播报内容或使用人姓名。")

        raw_speed = payload.get("speed")
        try:
            speed = float(raw_speed) if raw_speed not in (None, "") else None
        except (TypeError, ValueError):
            speed = None
        # Audio generation belongs to the host now. The QSM board only receives
        # the resulting PCM stream for speaker playback and keeps its ASR/local
        # inquiry resources available.
        return get_host_offline_tts().speak_sync(
            text[:240],
            volume=CloudSyncWorker._int(payload.get("volume")),
            speed=speed,
        )

    @staticmethod
    def _upsert_medicine(payload: dict[str, object]) -> dict[str, object]:
        slot = CloudSyncWorker._int(payload.get("slot"))
        name = str(payload.get("name") or "").strip()
        if slot is None or not 1 <= slot <= 23 or not name:
            raise CloudSyncError("补药命令缺少有效仓位或药品名称。")
        repository = MedicineRepository()
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM medicines WHERE hardware_slot=?", (slot,)).fetchone()
        if row:
            updated = repository.update(
                str(row["id"]),
                {
                    "name": name,
                    "barcode": payload.get("barcode") or payload.get("code") or "",
                    "category": payload.get("category") or payload.get("spec") or "家庭常用",
                    "stock": CloudSyncWorker._int(payload.get("quantity") or payload.get("stock")) or 1,
                    "unit": payload.get("unit") or "盒",
                    "expire_date": payload.get("expireDate") or payload.get("expire_date") or "",
                },
            )
        else:
            updated = repository.create_from_scan(
                barcode=str(payload.get("barcode") or payload.get("code") or ""),
                name=name,
                spec=str(payload.get("spec") or ""),
                expire_date=str(payload.get("expireDate") or payload.get("expire_date") or ""),
                stock=CloudSyncWorker._int(payload.get("quantity") or payload.get("stock")) or 1,
                unit=str(payload.get("unit") or "盒"),
                category=str(payload.get("category") or "家庭常用"),
                hardware_slot=slot,
            )
        return {"medicine": updated.model_dump(mode="json") if updated else None}

    @staticmethod
    def _upsert_service_user(payload: dict[str, object]) -> dict[str, object]:
        from .records_service import RecordsService

        service = RecordsService()
        user_id = str(payload.get("id") or "").strip()
        existing = next((item for item in service.list_service_users() if item.id == user_id), None)
        if existing:
            user = service.update_service_user(user_id, ServiceUserUpdateRequest(**payload))
        else:
            user = service.create_service_user(ServiceUserCreateRequest(**payload))
        return {"user": user.model_dump(mode="json")}

    @staticmethod
    def _upsert_today_plan(payload: dict[str, object]) -> dict[str, object]:
        from .records_service import RecordsService

        service = RecordsService()
        plan_id = str(payload.get("id") or "").strip()
        existing = next((item for item in service.list_today_plans() if item.id == plan_id), None)
        if existing:
            plan = service.update_today_plan(plan_id, TodayPlanUpdateRequest(**payload))
        else:
            plan = service.create_today_plan(TodayPlanCreateRequest(**payload))
        return {"plan": plan.model_dump(mode="json")}

    @staticmethod
    def _open_cabinet(payload: dict[str, object], command: dict[str, object]) -> dict[str, object]:
        if not settings.cloud_remote_cabinet_enabled:
            raise CloudSyncError("远程开柜功能未启用。")
        if payload.get("remote_confirmed") is not True:
            raise CloudSyncError("远程开柜缺少明确确认。")
        source_identity = str(command.get("sourceOpenId") or command.get("_openid") or "").strip()
        if not source_identity:
            raise CloudSyncError("远程开柜命令缺少小程序身份。")
        slot = CloudSyncWorker._int(payload.get("slot"))
        if slot is None or not 1 <= slot <= 23:
            raise CloudSyncError("远程开柜仓位无效。")
        if CloudSyncWorker._recent_remote_open(slot):
            raise CloudSyncError("同一仓位刚刚已执行远程开柜，重复请求已拒绝。")
        response = DispenseService().open_cabinet(
            DispenseOpenRequest(
                slot=slot,
                quantity=max(1, CloudSyncWorker._int(payload.get("quantity")) or 1),
                reason=str(payload.get("reason") or "家属端远程开柜"),
                confirmed_open=True,
                medicine_id=str(payload.get("medicine_id") or "") or None,
                target_user_id=str(payload.get("target_user_id") or ""),
                target_user_name=str(payload.get("target_user_name") or payload.get("actor_name") or "家属端"),
            )
        )
        return response.model_dump(mode="json")

    @staticmethod
    def _recent_remote_open(slot: int, seconds: int = 10) -> bool:
        from datetime import datetime

        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT result_json, updated_at
                FROM cloud_command_history
                WHERE command_type='OPEN_CABINET' AND status IN ('done', 'done_unacked')
                ORDER BY updated_at DESC LIMIT 8
                """
            ).fetchall()
        now = datetime.now()
        for row in rows:
            try:
                age = (now - datetime.strptime(str(row["updated_at"]), "%Y-%m-%d %H:%M:%S")).total_seconds()
                result = json.loads(row["result_json"] or "{}")
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if age > seconds:
                continue
            if int(result.get("slot") or 0) == slot:
                return True
        return False

    def _ack(self, command_id: str, status: str, result: dict[str, object]) -> None:
        self._call("ACK_COMMAND", {"commandId": command_id, "status": status, "result": result})

    @staticmethod
    def _command_history(command_id: str):
        db.init_db()
        with db.connect() as conn:
            return conn.execute(
                "SELECT status, result_json, created_at FROM cloud_command_history WHERE command_id=?",
                (command_id,),
            ).fetchone()

    @staticmethod
    def _save_command(command_id: str, command_type: str, status: str, result: dict[str, object], created_at: str) -> None:
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO cloud_command_history(command_id, command_type, status, result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(command_id) DO UPDATE SET
                  status=excluded.status, result_json=excluded.result_json, updated_at=excluded.updated_at
                """,
                (command_id, command_type, status, json.dumps(result, ensure_ascii=False), created_at, db.now_text()),
            )

    @staticmethod
    def _int(value: object) -> int | None:
        try:
            return int(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            return None


cloud_sync_worker = CloudSyncWorker()
