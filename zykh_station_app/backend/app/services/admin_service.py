from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import uuid4

from .. import db
from ..config import APP_ROOT, settings
from ..schemas.admin import AdminAuditRecord
from ..schemas.medicine import MedicineUpdateRequest
from ..schemas.records import ServiceUserCreateRequest, ServiceUserUpdateRequest, TodayPlanCreateRequest, TodayPlanUpdateRequest
from ..schemas.settings import BasicSettingsResponse, BasicSettingsUpdateRequest
from ..repositories.inquiry_repository import InquiryRepository
from .dispense_archive_service import DispenseArchiveService
from .fingerprint_service import FingerprintService
from .identity_service import IdentityService
from .medicine_service import MedicineService
from .network_service import NetworkService
from .records_service import RecordsService
from .settings_service import SettingsService


class AdminServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AdminService:
    _log_sources = {
        "backend": ("后端服务", APP_ROOT / "data" / "run" / "backend.log"),
        "frontend": ("前端服务", APP_ROOT / "data" / "run" / "frontend.log"),
        "browser": ("浏览器", APP_ROOT / "data" / "run" / "chromium.log"),
        "audio": ("音频转发", APP_ROOT / "data" / "run" / "audio-relay.log"),
        "cleanup": ("终端退出", APP_ROOT / "data" / "run" / "kiosk-cleanup.log"),
    }

    def overview(self) -> dict[str, object]:
        db.init_db()
        with db.connect() as conn:
            counts = {
                "users": int(conn.execute("SELECT COUNT(*) AS count FROM service_users").fetchone()["count"]),
                "medicines": int(conn.execute("SELECT COUNT(*) AS count FROM medicines WHERE stock > 0").fetchone()["count"]),
                "dispense_records": int(conn.execute("SELECT COUNT(*) AS count FROM dispense_records").fetchone()["count"]),
                "identity_archives": int(
                    conn.execute("SELECT COUNT(*) AS count FROM dispense_identity_archives WHERE status='captured'").fetchone()["count"]
                ),
                "pending_sync": int(conn.execute("SELECT pending_count FROM sync_state WHERE id=1").fetchone()["pending_count"]),
            }
        gateway_url = f"{settings.qsm_api_base}{settings.qsm_status_path}"
        status_urls = {
            "face": f"{settings.qsm_face_api_base}{settings.qsm_face_status_path}",
            "fingerprint": f"{settings.qsm_fingerprint_api_base}{settings.qsm_fingerprint_status_path}",
            "microphone": f"{settings.qsm_mic_api_base}{settings.qsm_mic_status_path}",
        }
        with ThreadPoolExecutor(max_workers=len(status_urls) + 2, thread_name_prefix="admin-status") as executor:
            status_jobs = {name: executor.submit(self._json_status, url) for name, url in status_urls.items()}
            gateway_job = executor.submit(self._tcp_status, gateway_url)
            network_job = executor.submit(NetworkService().status)
            status_results = {name: job.result() for name, job in status_jobs.items()}
            gateway = gateway_job.result()
            network = network_job.result()

        face = status_results["face"]
        camera_available = bool(face.get("ok") and face.get("camera_available"))
        devices = {
            "gateway": gateway,
            "camera": {
                "ok": camera_available,
                "status": "available" if camera_available else "unavailable",
                "error_message": "" if camera_available else face.get("error_message") or "摄像头未被识别服务检测到。",
            },
            "face": face,
            "fingerprint": status_results["fingerprint"],
            "microphone": status_results["microphone"],
        }
        return {
            "ok": True,
            "generated_at": db.now_text(),
            "host": self._host_metrics(),
            "counts": counts,
            "devices": devices,
            "network": network,
            "recent_audit": self.recent_audit(8),
            "recent_dispense_archives": DispenseArchiveService().list_recent(6),
        }

    def network_settings(self) -> BasicSettingsResponse:
        return SettingsService().get()

    def update_network_settings(
        self,
        *,
        wifi_enabled: bool | None = None,
        sim_enabled: bool | None = None,
    ) -> BasicSettingsResponse:
        response = SettingsService().update(
            BasicSettingsUpdateRequest(
                wifi_enabled=wifi_enabled,
                sim_enabled=sim_enabled,
            )
        )
        changed = []
        if wifi_enabled is not None:
            changed.append(f"wifi={'on' if wifi_enabled else 'off'}")
        if sim_enabled is not None:
            changed.append(f"sim={'on' if sim_enabled else 'off'}")
        self.audit(
            "network.update",
            "physical-network",
            "success" if not response.warnings else "warning",
            ", ".join(changed) or "no-change",
        )
        return response

    def list_users(self) -> tuple[list, dict[str, dict[str, object]]]:
        users = RecordsService().list_service_users()
        db.init_db()
        with db.connect() as conn:
            faces = {
                str(row["service_user_id"]): dict(row)
                for row in conn.execute(
                    "SELECT service_user_id, subject, match_count, last_seen_at FROM face_identities"
                )
            }
            fingerprints = {
                str(row["service_user_id"]): dict(row)
                for row in conn.execute(
                    "SELECT service_user_id, template_id, match_count, last_seen_at FROM fingerprint_identities"
                )
            }
        biometrics = {
            user.id: {
                "face_enrolled": user.id in faces,
                "face_subject": faces.get(user.id, {}).get("subject", ""),
                "face_match_count": int(faces.get(user.id, {}).get("match_count", 0)),
                "face_last_seen_at": faces.get(user.id, {}).get("last_seen_at", ""),
                "fingerprint_enrolled": user.id in fingerprints,
                "fingerprint_template_id": fingerprints.get(user.id, {}).get("template_id"),
                "fingerprint_match_count": int(fingerprints.get(user.id, {}).get("match_count", 0)),
                "fingerprint_last_seen_at": fingerprints.get(user.id, {}).get("last_seen_at", ""),
            }
            for user in users
        }
        return users, biometrics

    def create_user(self, request: ServiceUserCreateRequest) -> None:
        user = RecordsService().create_service_user(request)
        self.audit("user.create", user.id, "success", user.name)

    def update_user(self, user_id: str, request: ServiceUserUpdateRequest) -> None:
        try:
            user = RecordsService().update_service_user(user_id, request)
        except ValueError as exc:
            raise AdminServiceError(str(exc), 404) from exc
        self.audit("user.update", user_id, "success", user.name)

    def delete_user(self, user_id: str, confirmation: str) -> None:
        users = {user.id: user for user in RecordsService().list_service_users()}
        user = users.get(user_id)
        if user is None:
            raise AdminServiceError("服务对象不存在。", 404)
        if confirmation.strip() != f"DELETE {user.name}":
            raise AdminServiceError("删除服务对象的二次确认校验失败。")
        fingerprint_result = FingerprintService().delete_user(user_id)
        try:
            RecordsService().delete_service_user(user_id)
        except ValueError as exc:
            raise AdminServiceError(str(exc), 404) from exc
        detail = user.name
        if not fingerprint_result.ok:
            detail += f"；板端指纹删除未确认：{fingerprint_result.message}"
        self.audit("user.delete", user_id, "success", detail)

    def enroll_face(self, user_id: str) -> object:
        result = IdentityService().enroll_user(user_id, samples=18)
        self.audit("face.enroll", user_id, "success" if result.ok else "failed", result.message)
        return result

    def unbind_face(self, user_id: str, confirmation: str) -> str:
        if confirmation.strip() != "REMOVE FACE":
            raise AdminServiceError("解除人脸绑定的二次确认校验失败。")
        with db.connect() as conn:
            row = conn.execute("SELECT subject FROM face_identities WHERE service_user_id=?", (user_id,)).fetchone()
            conn.execute("DELETE FROM face_identities WHERE service_user_id=?", (user_id,))
        message = "本机人脸绑定已解除。板端样本如需物理删除，请使用板端维护工具。"
        self.audit("face.unbind", user_id, "success", str(row["subject"]) if row else "not-bound")
        return message

    def enroll_fingerprint(self, user_id: str) -> object:
        result = FingerprintService().start_enrollment(user_id, timeout=60)
        self.audit("fingerprint.enroll.start", user_id, "success" if result.ok else "failed", result.message)
        return result

    def fingerprint_enrollment_progress(self, user_id: str, job_id: str) -> object:
        result = FingerprintService().enrollment_progress(user_id, job_id)
        if result.status in {"enrolled", "error", "timeout", "not_found"}:
            self.audit("fingerprint.enroll.finish", user_id, "success" if result.ok else "failed", result.message)
        return result

    def delete_fingerprint(self, user_id: str, confirmation: str) -> object:
        if confirmation.strip() != "REMOVE FINGERPRINT":
            raise AdminServiceError("删除指纹的二次确认校验失败。")
        result = FingerprintService().delete_user(user_id)
        self.audit("fingerprint.delete", user_id, "success" if result.ok else "failed", result.message)
        return result

    def list_medicines(self) -> list:
        return MedicineService().list_medicines().medicines

    def update_medicine(self, medicine_id: str, request: MedicineUpdateRequest) -> object:
        result = MedicineService().update_medicine(medicine_id, request)
        if result is None:
            raise AdminServiceError("药品不存在。", 404)
        self.audit("medicine.update", medicine_id, "success", result.medicine.name)
        return result.medicine

    def list_today_plans(self) -> tuple[list, list, list]:
        records = RecordsService()
        return records.list_today_plans(due_only=False), records.list_service_users(), self.list_medicines()

    def create_today_plan(self, request: TodayPlanCreateRequest) -> object:
        try:
            plan = RecordsService().create_today_plan(request)
        except ValueError as exc:
            raise AdminServiceError(str(exc)) from exc
        self.audit("today-plan.create", plan.id, "success", f"{plan.target_user} {plan.time} {plan.medicine}")
        return plan

    def update_today_plan(self, plan_id: str, request: TodayPlanUpdateRequest) -> object:
        try:
            plan = RecordsService().update_today_plan(plan_id, request)
        except ValueError as exc:
            raise AdminServiceError(str(exc), 404 if "不存在" in str(exc) else 400) from exc
        self.audit("today-plan.update", plan.id, "success", f"{plan.target_user} {plan.time} {plan.medicine}")
        return plan

    def delete_today_plan(self, plan_id: str, confirmation: str) -> None:
        if confirmation.strip() != "DELETE PLAN":
            raise AdminServiceError("删除计划的二次确认校验失败。")
        try:
            plan = RecordsService().get_today_plan(plan_id)
            RecordsService().delete_today_plan(plan_id)
        except ValueError as exc:
            raise AdminServiceError(str(exc), 404) from exc
        self.audit("today-plan.delete", plan_id, "success", f"{plan.target_user} {plan.time} {plan.medicine}")

    def open_cabinet(
        self,
        slot: int,
        confirmation: str,
        reason: str,
        request_id: str,
    ) -> object:
        del slot, confirmation, reason, request_id
        raise AdminServiceError(
            "旧版 1-23 仓位开柜入口已停用；请从现场取药流程按药品点亮对应分类柜。",
            410,
        )

    def system_action(self, action: str, confirmation: str) -> dict[str, object]:
        if not settings.admin_allow_system_actions:
            raise AdminServiceError("当前部署已禁用系统控制。", 403)
        normalized = action.strip().lower()
        confirmations = {
            "screen_on": "SCREEN ON",
            "screen_off": "SCREEN OFF",
            "restart_app": "RESTART APP",
            "reboot": "REBOOT DEVICE",
        }
        if normalized not in confirmations:
            raise AdminServiceError("不支持该系统操作。")
        if confirmation.strip() != confirmations[normalized]:
            raise AdminServiceError("系统操作的二次确认校验失败。")

        if normalized in {"screen_on", "screen_off"}:
            result = self._screen_power(normalized == "screen_on")
            self.audit(f"system.{normalized}", "display", "success" if result[0] else "failed", result[1])
            return {"ok": result[0], "accepted": result[0], "action": normalized, "message": result[1]}

        command = settings.admin_restart_command if normalized == "restart_app" else settings.admin_reboot_command
        threading.Thread(target=self._run_delayed, args=(command,), daemon=True).start()
        message = "应用将在两秒后重新启动。" if normalized == "restart_app" else "设备将在两秒后重新启动。"
        self.audit(f"system.{normalized}", "host", "accepted", message)
        return {"ok": True, "accepted": True, "action": normalized, "message": message}

    def logs(self, source: str, limit: int = 300) -> dict[str, object]:
        sources = [
            {
                "id": source_id,
                "label": label,
                "available": path.is_file(),
                "size": path.stat().st_size if path.is_file() else 0,
            }
            for source_id, (label, path) in self._log_sources.items()
        ]
        selected = source if source in self._log_sources else "backend"
        label, path = self._log_sources[selected]
        lines: list[str] = []
        if path.is_file():
            try:
                raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(20, min(limit, 1000)) :]
                lines = [self._redact(line) for line in raw_lines]
            except OSError as exc:
                lines = [f"日志读取失败：{exc}"]
        return {
            "ok": True,
            "source": selected,
            "label": label,
            "lines": lines,
            "updated_at": db.now_text(),
            "sources": sources,
        }

    def inquiry_history(self, limit: int = 40) -> dict[str, object]:
        sessions = InquiryRepository().list_sessions(limit=max(1, min(limit, 100)))
        repeated = sum(1 for session in sessions if self._has_repeated_assistant_question(session.messages))
        return {
            "ok": True,
            "sessions": sessions,
            "repeated_question_sessions": repeated,
        }

    @staticmethod
    def _has_repeated_assistant_question(messages) -> bool:
        questions = [
            message.content.strip()
            for message in messages
            if message.role == "assistant" and ("？" in message.content or "?" in message.content)
        ]
        return len(questions) != len(set(questions))

    def audit(self, action: str, target: str, result: str, detail: str) -> None:
        db.init_db()
        safe_detail = self._redact(detail)[:600]
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO admin_audit_records(id, created_at, actor, action, target, result, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"audit-{uuid4().hex[:14]}", db.now_text(), "admin", action, target, result, safe_detail),
            )

    def recent_audit(self, limit: int = 20) -> list[AdminAuditRecord]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, actor, action, target, result, detail FROM admin_audit_records ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [AdminAuditRecord(**dict(row)) for row in rows]

    @staticmethod
    def _json_status(url: str) -> dict[str, object]:
        try:
            with urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                return {**payload, "ok": bool(payload.get("ok", True))}
            return {"ok": False, "status": "invalid"}
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "status": "unavailable", "error_message": str(exc)}

    @staticmethod
    def _tcp_status(url: str) -> dict[str, object]:
        parsed = urlsplit(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=0.8):
                return {"ok": True, "status": "available", "host": host, "port": port}
        except OSError as exc:
            return {"ok": False, "status": "unavailable", "error_message": str(exc), "host": host, "port": port}

    @staticmethod
    def _host_metrics() -> dict[str, object]:
        uptime_seconds = 0
        try:
            uptime_seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
        except (OSError, ValueError, IndexError):
            pass
        memory_total = memory_available = 0
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024
            memory_total = values.get("MemTotal", 0)
            memory_available = values.get("MemAvailable", 0)
        except (OSError, ValueError, IndexError):
            pass
        disk = shutil.disk_usage(APP_ROOT)
        try:
            load = os.getloadavg()
        except OSError:
            load = (0.0, 0.0, 0.0)
        return {
            "hostname": os.uname().nodename,
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "uptime_seconds": uptime_seconds,
            "load": [round(value, 2) for value in load],
            "memory_total": memory_total,
            "memory_used": max(0, memory_total - memory_available),
            "disk_total": disk.total,
            "disk_used": disk.used,
        }

    @staticmethod
    def _screen_power(on: bool) -> tuple[bool, str]:
        env = os.environ.copy()
        env["DISPLAY"] = settings.display_name
        if settings.display_xauthority:
            env["XAUTHORITY"] = settings.display_xauthority
        command = ["xset", "-display", settings.display_name, "dpms", "force", "on" if on else "off"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=4, check=False, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"显示控制失败：{exc}"
        if result.returncode == 0:
            return True, "屏幕已唤醒。" if on else "屏幕已关闭，触摸或键盘操作可再次唤醒。"
        return False, f"显示控制失败：{(result.stderr or '').strip()[:180]}"

    @staticmethod
    def _run_delayed(command: str) -> None:
        time.sleep(2)
        try:
            subprocess.Popen(["sh", "-lc", command], start_new_session=True)
        except OSError:
            return

    @staticmethod
    def _redact(value: str) -> str:
        text = str(value or "")
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-***", text)
        text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1***", text)
        text = re.sub(r"(?i)((?:api[_-]?key|token|secret)\s*[=:]\s*)[^\s,;]+", r"\1***", text)
        return text
