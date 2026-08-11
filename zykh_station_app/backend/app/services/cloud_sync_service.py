from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .. import db
from ..config import settings
from ..modules.presentation_mode import PresentationModePolicy
from ..repositories.dispense_repository import DispenseRepository
from ..repositories.inquiry_repository import InquiryRepository
from ..repositories.medicine_repository import MedicineRepository
from ..repositories.sync_repository import SyncRepository
from ..schemas.medicine import MedicineUpdateRequest
from ..schemas.records import (
    ServiceUser,
    ServiceUserCreateRequest,
    ServiceUserUpdateRequest,
    TodayPlanCreateRequest,
    TodayPlanUpdateRequest,
)
from ..schemas.sync import SyncStatus
from .ai_service import AiService
from .medication_safety_outbox import MedicationSafetyOutbox
from .qsm_client import QsmClient
from .speech_service import SpeechService


REMOTE_CABINET_DISABLED_ERROR = "远程开柜已禁用，请在终端现场完成身份确认和用药核查。"


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
        self._cloud_capabilities: dict[str, object] = {}
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
        realtime_enabled = self._realtime_enabled()
        with self._state_lock:
            return base.model_copy(
                update={
                    "connected": self._connected if realtime_enabled else False,
                    "device_id": settings.cloud_sync_device_id,
                    "last_error": self._last_error if realtime_enabled else "",
                    "last_command_at": self._last_command_at,
                    "interval_seconds": settings.cloud_sync_interval_seconds,
                }
            )

    def run_once(self) -> tuple[int, str]:
        if not settings.cloud_sync_enabled:
            raise CloudSyncError("云同步已关闭。")
        if not self._realtime_enabled():
            with self._state_lock:
                self._connected = False
                self._last_error = ""
            raise CloudSyncError("本地模式已暂停微信小程序实时连接。")
        if not self._run_lock.acquire(blocking=False):
            return 0, "同步正在进行。"
        try:
            self._flush_unacked_commands()
            commands = self._request("PULL_COMMANDS", {"limit": 10, "agentVersion": 2})
            if not isinstance(commands, list):
                commands = commands.get("commands", []) if isinstance(commands, dict) else []
            for command in commands:
                self._ensure_realtime_enabled()
                self._handle_command(command)

            snapshot = self._build_snapshot()
            from .network_service import NetworkService

            network_status = NetworkService().status()
            self._request(
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
            safety_events_sent = MedicationSafetyOutbox().flush(
                self._request,
                capabilities=self._cloud_capabilities,
            )
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
            synced_count += safety_events_sent

            now = db.now_text()
            current = SyncRepository().get_status()
            pending_safety_events = MedicationSafetyOutbox().pending_count()
            SyncRepository().save_status(
                SyncStatus(
                    sync_status="已同步" if pending_safety_events == 0 else "待同步",
                    pending_count=pending_safety_events,
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

    @staticmethod
    def _realtime_enabled() -> bool:
        mode = db.get_setting("network_mode", settings.network_preferred_mode).strip().lower()
        return PresentationModePolicy.resolve(mode).realtime_sync_enabled

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

    def _request(self, action: str, data: dict[str, object]) -> Any:
        self._ensure_realtime_enabled()
        return self._call(action, data)

    def issue_pairing_code_hash(self, payload: dict[str, object]) -> Any:
        """Publish a hash-only pairing credential through the authenticated device port."""
        self._ensure_realtime_enabled()
        if not settings.cloud_sync_endpoint.strip():
            raise CloudSyncError("云端配对服务未配置。")
        if not self._device_secret():
            raise CloudSyncError("设备云端密钥未配置。")
        return self._call("ISSUE_DEVICE_PAIRING_CODE", payload)

    def _ensure_realtime_enabled(self) -> None:
        if not self._realtime_enabled():
            raise CloudSyncError("本地模式已暂停微信小程序实时连接。")

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
            cloud_inventory_state = {
                "AVAILABLE": "STOCKED",
                "DEPLETED": "DEPLETED",
                "UNKNOWN": "UNKNOWN",
            }.get(medicine.inventory_state, "UNKNOWN")
            cloud_quantity = 0 if cloud_inventory_state == "DEPLETED" else 1
            row.update(
                {
                    "slot": medicine.hardware_slot,
                    "hardwareSlot": medicine.hardware_slot,
                    "spec": medicine.spec,
                    "traceCode": medicine.trace_code,
                    "stock": cloud_quantity,
                    "quantity": cloud_quantity,
                    "inventoryState": cloud_inventory_state,
                    "inventory_state": cloud_inventory_state,
                    "inventoryStateRevision": medicine.inventory_revision,
                    "inventory_state_revision": medicine.inventory_revision,
                    "inventoryConfirmedAt": medicine.inventory_confirmed_at,
                    "expireDate": medicine.expire_date,
                    "expiryPrecision": CloudSyncWorker._expiry_precision(medicine.expire_date),
                    "lowStockLine": medicine.low_stock_line,
                }
            )
            medicines.append(row)

        records_service = RecordsService()
        service_users = CloudSyncWorker._service_user_sync_projection()
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
                       error_message, measured_at, source_route, inquiry_session_id,
                       attribution_source, service_user_id, service_user_name_snapshot,
                       persona_generation
                FROM vitals_records
                WHERE source NOT LIKE '%SpO2-demo%'
                  AND sensor_model NOT LIKE '%SpO2-demo%'
                ORDER BY measured_at DESC LIMIT 100
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
                    "sourceRoute": row["source_route"],
                    "inquirySessionId": row["inquiry_session_id"],
                    "attributionSource": row["attribution_source"],
                    "serviceUserId": row["service_user_id"],
                    "serviceUserNameSnapshot": row["service_user_name_snapshot"],
                    "personaGeneration": row["persona_generation"],
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
    def _service_user_sync_projection() -> list[dict[str, object]]:
        """Project active people and archived ownership tombstones for CloudBase."""
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, age, profile, allergies, note, status,
                       medical_conditions_json, current_medications_json,
                       allergy_facts_json, safety_profile_revision,
                       safety_profile_updated_at, persona_generation, archived
                FROM service_users
                ORDER BY id
                """
            ).fetchall()

        def json_list(value: object) -> list[dict[str, object]]:
            try:
                parsed = json.loads(str(value or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                return []
            return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []

        return [
            ServiceUser(
                id=str(row["id"]),
                name=str(row["name"]),
                age=int(row["age"] or 0),
                profile=str(row["profile"] or ""),
                allergies=str(row["allergies"] or ""),
                note=str(row["note"] or ""),
                status=str(row["status"] or ""),
                medical_conditions=json_list(row["medical_conditions_json"]),
                current_medications=json_list(row["current_medications_json"]),
                allergy_facts=json_list(row["allergy_facts_json"]),
                safety_profile_revision=max(1, int(row["safety_profile_revision"] or 1)),
                safety_profile_updated_at=str(row["safety_profile_updated_at"] or ""),
                persona_generation=str(row["persona_generation"] or ""),
                archived=bool(row["archived"]),
            ).model_dump(mode="json")
            for row in rows
        ]

    @staticmethod
    def _cloud_record_actor(name: str, user_type: str) -> str:
        if user_type == "guest":
            return name if str(name).startswith("游客") else f"游客（{name or '未登记'}）"
        return name or "家庭成员"

    def _sync_snapshot(self, snapshot: dict[str, list[dict[str, object]]]) -> int:
        if self._cloud_schema_version < 2:
            return self._sync_snapshot_v1(snapshot)

        synced = 0
        # Inquiry and vitals snapshots are intentionally bounded history
        # windows.  Finalizing either window would make CloudBase delete every
        # older row that was simply outside this upload, so those two kinds are
        # append/update only.
        finalize_kinds = {"medicines", "serviceUsers", "plans", "records"}
        for key in ("medicines", "serviceUsers", "plans", "inquiries", "vitals", "records"):
            ids: list[str] = []
            for rows in self._snapshot_batches(snapshot.get(key, [])):
                result = self._request("UPSERT_SNAPSHOT_BATCH", {"kind": key, "rows": rows})
                if isinstance(result, dict):
                    ids.extend(str(value) for value in result.get("ids", []))
                    synced += int(result.get("count") or 0)
            if key in finalize_kinds:
                self._request("FINALIZE_SNAPSHOT", {"kind": key, "ids": ids})
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
            ping = self._request("PING", {})
            self._cloud_schema_version = int(ping.get("schemaVersion") or 1) if isinstance(ping, dict) else 1
            self._cloud_schema_revision = str(ping.get("schemaRevision") or "") if isinstance(ping, dict) else ""
            capabilities = ping.get("capabilities") if isinstance(ping, dict) else {}
            self._cloud_capabilities = dict(capabilities) if isinstance(capabilities, dict) else {}
            self._cloud_schema_checked_at = now
        return self._cloud_schema_version

    def _sync_snapshot_v1(self, snapshot: dict[str, list[dict[str, object]]]) -> int:
        synced = 0
        self._request("UPLOAD_MEDICINES", {"medicines": snapshot.get("medicines", [])})
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
        active_service_users = [
            row
            for row in snapshot.get("serviceUsers", [])
            if not bool(row.get("archived"))
        ]
        counts = {key: len(value) for key, value in snapshot.items()}
        counts["serviceUsers"] = len(active_service_users)
        return {
            "counts": counts,
            "serviceUsers": active_service_users,
            "serviceUsersSnapshotComplete": True,
            "plans": snapshot.get("plans", []),
            "recentInquiries": [
                {
                    "inquiry_id": row.get("inquiry_id") or row.get("session_id"),
                    "session_id": row.get("session_id") or row.get("inquiry_id"),
                    "target_user_id": row.get("target_user_id") or row.get("user_id"),
                    "target_user_name": row.get("target_user_name") or row.get("user_name"),
                    "persona_generation": row.get("persona_generation")
                    or row.get("personaGeneration"),
                    "title": row.get("title"),
                    "risk_level": row.get("risk_level"),
                    "risk_label": row.get("risk_label"),
                    "symptoms_summary": row.get("symptoms_summary"),
                    "reply": row.get("reply") or row.get("ai_message"),
                    "messageCount": len(row.get("messages") or [])
                    if isinstance(row.get("messages"), list)
                    else max(0, CloudSyncWorker._int(row.get("messageCount")) or 0),
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
        self._request(action, payload)
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
        if command_type == "OPEN_CABINET":
            result = {"error": REMOTE_CABINET_DISABLED_ERROR}
            created_at = str(existing["created_at"] if existing else db.now_text())
            self._save_command(command_id, command_type, "failed_unacked", result, created_at)
            try:
                self._ack(command_id, "failed", result)
            except CloudSyncError:
                raise
            self._save_command(command_id, command_type, "failed", result, created_at)
            return
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
            if str(row["command_type"]) == "OPEN_CABINET":
                final_status = "failed"
                result = {"error": REMOTE_CABINET_DISABLED_ERROR}
                self._save_command(
                    str(row["command_id"]),
                    str(row["command_type"]),
                    "failed_unacked",
                    result,
                    str(row["created_at"]),
                )
            else:
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
        if command_type in {"AI_CHAT", "UPSERT_SERVICE_USER", "UPSERT_TODAY_PLAN"}:
            self._require_current_command_persona(command_type, payload)
        if command_type == "AUDIO_BEEP":
            return QsmClient().audio_beep(self._int(payload.get("volume")))
        if command_type == "AUDIO_SPEAK":
            return self._speak_reminder(payload)
        if command_type == "READ_VITALS_ALL":
            return self._read_remote_vitals(command, payload)
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
            raise CloudSyncError(REMOTE_CABINET_DISABLED_ERROR)
        raise CloudSyncError(f"不支持的云端命令：{command_type}")

    @staticmethod
    def _require_current_command_persona(
        command_type: str,
        payload: dict[str, object],
    ) -> dict[str, str]:
        if command_type == "UPSERT_SERVICE_USER":
            person_id = str(
                payload.get("id")
                or payload.get("service_user_id")
                or payload.get("serviceUserId")
                or ""
            ).strip()
        else:
            person_id = str(
                payload.get("service_user_id")
                or payload.get("serviceUserId")
                or payload.get("target_user_id")
                or payload.get("targetUserId")
                or payload.get("user_id")
                or payload.get("userId")
                or payload.get("person_id")
                or payload.get("personId")
                or ""
            ).strip()
        generation = str(
            payload.get("persona_generation")
            or payload.get("personaGeneration")
            or ""
        ).strip()
        if not person_id or not generation:
            raise CloudSyncError("人物命令缺少当前人物代次，已拒绝执行。")
        db.init_db()
        with db.connect() as conn:
            person = conn.execute(
                """
                SELECT name, persona_generation
                FROM service_users
                WHERE id=? AND archived=0
                """,
                (person_id,),
            ).fetchone()
        if (
            person is None
            or str(person["persona_generation"] or "").strip() != generation
        ):
            raise CloudSyncError("人物代次已经变化，已拒绝执行该云端命令。")
        return {
            "service_user_id": person_id,
            "service_user_name_snapshot": str(person["name"] or "").strip(),
            "persona_generation": generation,
        }

    @classmethod
    def _read_remote_vitals(
        cls,
        command: dict[str, object],
        payload: dict[str, object],
    ) -> dict[str, object]:
        from ..routers.qsm import read_qsm_vitals

        attribution_source = cls._command_text_value(
            payload,
            "attribution_source",
            "attribution_source",
            "attributionSource",
        ).upper()
        person_id = cls._command_text_value(
            payload,
            "service_user_id",
            "service_user_id",
            "serviceUserId",
            "person_id",
            "personId",
            "target_user_id",
            "targetUserId",
        )
        generation = cls._command_text_value(
            payload,
            "persona_generation",
            "persona_generation",
            "personaGeneration",
        )
        inquiry_session_id = cls._command_text_value(
            payload,
            "inquiry_session_id",
            "inquiry_session_id",
            "inquirySessionId",
        )

        if attribution_source == "STANDALONE":
            if person_id or generation:
                raise CloudSyncError("独立测量不得携带人物或人物代次。")
            context = {
                "service_user_id": "",
                "service_user_name_snapshot": "",
                "persona_generation": "",
            }
        elif attribution_source == "REMOTE_COMMAND":
            if not person_id or not generation:
                raise CloudSyncError("远程人物体征缺少当前人物代次，已拒绝执行。")
            context = cls._require_current_command_persona("READ_VITALS_ALL", payload)
        else:
            raise CloudSyncError("远程体征必须明确人物归属或标记为独立测量。")

        command_id = str(command.get("_id") or command.get("id") or "").strip()
        operation_identity = command_id or json.dumps(
            {
                "payload": payload,
                "type": "READ_VITALS_ALL",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        operation_digest = hashlib.sha256(operation_identity.encode("utf-8")).hexdigest()
        record_id = f"vitals-command-{operation_digest[:24]}"
        response = read_qsm_vitals(
            full=True,
            record_id=record_id,
            source_route="HOME",
            inquiry_session_id=inquiry_session_id,
            attribution_source=attribution_source,
            service_user_id=context["service_user_id"],
            service_user_name_snapshot=context["service_user_name_snapshot"],
            persona_generation=context["persona_generation"],
        )
        result = response.model_dump(mode="json")
        result.update(
            {
                "vitals_record_id": record_id,
                "source_route": "HOME",
                "inquiry_session_id": inquiry_session_id,
                "attribution_source": attribution_source,
                **context,
            }
        )
        return result

    @staticmethod
    def _command_text_value(
        payload: dict[str, object],
        label: str,
        *names: str,
    ) -> str:
        values = [str(payload[name] or "").strip() for name in names if name in payload]
        if not values:
            return ""
        if len(set(values)) > 1:
            raise CloudSyncError(f"云端命令字段 {label} 存在冲突值。")
        return values[0]

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
        return SpeechService().speak_sync(
            text[:240],
            volume=CloudSyncWorker._int(payload.get("volume")),
            speed=speed,
        )

    @staticmethod
    def _upsert_medicine(payload: dict[str, object]) -> dict[str, object]:
        operation = str(payload.get("operation") or "upsert").strip().lower()
        if operation not in {"upsert", "patch"}:
            raise CloudSyncError(f"不支持的药品操作：{operation or '空'}。")
        nested_patch = payload.get("patch")
        if operation == "patch" and not isinstance(nested_patch, dict):
            raise CloudSyncError("药品补丁缺少 patch 字段。")
        source = nested_patch if operation == "patch" else payload
        assert isinstance(source, dict)
        remote_review_status = str(source.get("safety_review_status") or "").strip().lower()
        if remote_review_status and remote_review_status != "draft":
            raise CloudSyncError("药品安全资料不能远程标记为已审核。")
        if any(
            str(source.get(field) or "").strip()
            for field in ("safety_reviewed_by", "safety_reviewed_at")
        ):
            raise CloudSyncError("药品安全资料不能远程标记为已审核。")

        slot_present, slot_value = CloudSyncWorker._consistent_value(
            payload, "仓位", "hardware_slot", "hardwareSlot", "slot"
        )
        source_slot_present, source_slot_value = CloudSyncWorker._consistent_value(
            source, "仓位", "hardware_slot", "hardwareSlot", "slot"
        )
        if (
            source is not payload
            and slot_present
            and source_slot_present
            and str(slot_value).strip() != str(source_slot_value).strip()
        ):
            raise CloudSyncError("药品字段 仓位存在冲突值。")
        selected_slot = slot_value if slot_present else source_slot_value
        slot = CloudSyncWorker._int(selected_slot)
        if slot is None or not 1 <= slot <= 23:
            raise CloudSyncError("补药命令缺少有效仓位。")

        repository = MedicineRepository()
        existing = repository.get_by_hardware_slot(slot)
        updates: dict[str, object] = {}
        aliases = {
            "name": ("name",),
            "manufacturer": ("manufacturer",),
            "barcode": ("barcode", "code"),
            "category": ("category",),
            "spec": ("spec",),
            "trace_code": ("traceCode", "trace_code"),
            "stock": ("quantity", "stock"),
            "low_stock_line": ("lowStockLine", "low_stock_line"),
            "unit": ("unit",),
            "expire_date": ("expireDate", "expire_date"),
        }
        for target, names in aliases.items():
            present, value = CloudSyncWorker._consistent_value(source, names[0], *names)
            if not present or value is None:
                continue
            if target in {"stock", "low_stock_line"}:
                number = CloudSyncWorker._int(value)
                if number is None or number < 0:
                    raise CloudSyncError(f"药品字段 {names[0]} 必须是非负整数。")
                updates[target] = number
            else:
                updates[target] = str(value).strip()
        outer_inventory_state_present, outer_inventory_state = CloudSyncWorker._consistent_value(
            payload,
            "库存状态",
            "inventoryState",
            "inventory_state",
        )
        source_inventory_state_present, source_inventory_state = CloudSyncWorker._consistent_value(
            source,
            "库存状态",
            "inventoryState",
            "inventory_state",
        )
        if (
            source is not payload
            and outer_inventory_state_present
            and source_inventory_state_present
            and str(outer_inventory_state or "").strip().upper()
            != str(source_inventory_state or "").strip().upper()
        ):
            raise CloudSyncError("药品字段 库存状态存在冲突值。")
        inventory_state_present = source_inventory_state_present
        raw_inventory_state = source_inventory_state
        if inventory_state_present:
            cloud_inventory_state = str(raw_inventory_state or "").strip().upper()
            local_inventory_states = {
                "STOCKED": "AVAILABLE",
                "DEPLETED": "DEPLETED",
                "UNKNOWN": "UNKNOWN",
            }
            if cloud_inventory_state not in local_inventory_states:
                raise CloudSyncError("药品字段 inventoryState 必须是 STOCKED、DEPLETED 或 UNKNOWN。")
            requested_stock = updates.get("stock")
            if requested_stock is not None:
                quantity_conflicts = (
                    cloud_inventory_state == "DEPLETED" and int(requested_stock) != 0
                ) or (
                    cloud_inventory_state != "DEPLETED" and int(requested_stock) <= 0
                )
                if quantity_conflicts:
                    raise CloudSyncError("药品库存状态与 quantity 存在冲突。")
            updates["stock"] = 0 if cloud_inventory_state == "DEPLETED" else 1
            updates["inventory_state"] = local_inventory_states[cloud_inventory_state]
        elif "stock" in updates:
            if int(updates["stock"]) <= 0:
                raise CloudSyncError("quantity=0 必须同时明确 DEPLETED 库存状态。")
            updates["stock"] = 1
        for target in ("aliases", "active_ingredients"):
            if target not in source:
                continue
            value = source[target]
            if not isinstance(value, list):
                raise CloudSyncError(f"药品字段 {target} 必须是文本数组。")
            updates[target] = [
                str(item).strip()
                for item in value[:12]
                if str(item).strip()
            ]
        if "structured_contraindications" in source:
            value = source["structured_contraindications"]
            if not isinstance(value, list):
                raise CloudSyncError("药品字段 structured_contraindications 必须是对象数组。")
            structured: list[dict[str, str]] = []
            for item in value[:12]:
                if not isinstance(item, dict):
                    raise CloudSyncError("结构化禁忌项必须包含 concept_code 和 display_text。")
                concept_code = str(item.get("concept_code") or "").strip()
                display_text = str(item.get("display_text") or "").strip()
                if not concept_code or not display_text:
                    raise CloudSyncError("结构化禁忌项必须包含 concept_code 和 display_text。")
                structured.append(
                    {
                        "concept_code": concept_code[:60],
                        "display_text": display_text[:120],
                    }
                )
            updates["structured_contraindications"] = structured
        remote_draft_fields = {
            "aliases",
            "active_ingredients",
            "structured_contraindications",
            "safety_review_status",
        }
        if any(field in source for field in remote_draft_fields):
            updates.update(
                safety_review_status="draft",
                safety_reviewed_by="",
                safety_reviewed_at="",
                guidance_review_required=True,
            )
        for required_text in ("name", "category", "unit"):
            if required_text in updates and not str(updates[required_text]).strip():
                raise CloudSyncError(f"药品字段 {required_text} 不能为空。")
        if "expire_date" in updates:
            precision = CloudSyncWorker._expiry_precision(updates["expire_date"])
            if updates["expire_date"] and precision == "unknown":
                raise CloudSyncError("药品有效期必须是 YYYY-MM 或 YYYY-MM-DD。")
            precision_present, supplied_precision = CloudSyncWorker._consistent_value(
                source, "expiryPrecision", "expiryPrecision"
            )
            if precision_present and str(supplied_precision or "") != precision:
                raise CloudSyncError("expiryPrecision 与有效期格式不一致。")

        if existing:
            if operation == "patch" and not updates:
                raise CloudSyncError("药品补丁没有可更新字段。")
            updated = repository.update(
                existing.id,
                updates,
            )
        else:
            name = str(updates.get("name") or "").strip()
            if not name:
                raise CloudSyncError("新仓位药品缺少名称。")
            updated = repository.create_at_hardware_slot(
                hardware_slot=slot,
                barcode=str(updates.get("barcode") or ""),
                manufacturer=str(updates.get("manufacturer") or ""),
                name=name,
                spec=str(updates.get("spec") or ""),
                trace_code=str(updates.get("trace_code") or ""),
                expire_date=str(updates.get("expire_date") or ""),
                stock=int(updates["stock"]) if "stock" in updates else 1,
                low_stock_line=int(updates["low_stock_line"]) if "low_stock_line" in updates else 1,
                unit=str(updates.get("unit") or "盒"),
                category=str(updates.get("category") or "家庭常用"),
            )
            draft_updates = {
                field: updates[field]
                for field in (
                    "aliases",
                    "active_ingredients",
                    "structured_contraindications",
                    "safety_review_status",
                    "safety_reviewed_by",
                    "safety_reviewed_at",
                    "guidance_review_required",
                    "inventory_state",
                )
                if field in updates
            }
            if draft_updates:
                updated = repository.update(updated.id, draft_updates) or updated
        return {"medicine": updated.model_dump(mode="json") if updated else None}

    @staticmethod
    def _consistent_value(
        source: dict[str, object], label: str, *names: str
    ) -> tuple[bool, object | None]:
        values = [(name, source[name]) for name in names if name in source]
        if not values:
            return False, None
        normalized = {str(value).strip() for _, value in values}
        if len(normalized) > 1:
            raise CloudSyncError(f"药品字段 {label} 存在冲突值。")
        return True, values[0][1]

    @staticmethod
    def _expiry_precision(value: object) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return "day"
        if re.fullmatch(r"\d{4}-\d{2}", text):
            return "month"
        return "unknown"

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

    def _ack(self, command_id: str, status: str, result: dict[str, object]) -> None:
        self._request("ACK_COMMAND", {"commandId": command_id, "status": status, "result": result})

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
