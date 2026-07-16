from __future__ import annotations

from .. import db
from ..config import settings
from ..schemas.fingerprint import FingerprintActionResponse, FingerprintStatusResponse
from ..schemas.records import ServiceUser
from .qsm_fingerprint_client import QsmFingerprintClient


class FingerprintService:
    def __init__(self, client: QsmFingerprintClient | None = None) -> None:
        self.client = client or QsmFingerprintClient()

    def status(self) -> FingerprintStatusResponse:
        result = self.client.status()
        db.init_db()
        with db.connect() as conn:
            bound_users = int(conn.execute("SELECT COUNT(*) AS count FROM fingerprint_identities").fetchone()["count"])
            total_matches = int(
                conn.execute("SELECT COALESCE(SUM(match_count), 0) AS count FROM fingerprint_identities").fetchone()["count"]
            )
        return FingerprintStatusResponse(
            ok=bool(result.get("ok")),
            status=str(result.get("status") or ("available" if result.get("ok") else "unavailable")),
            device=str(result.get("device")) if result.get("device") else None,
            count=int(result.get("count") or 0),
            capacity=int(result.get("capacity") or 300),
            bound_users=bound_users,
            total_matches=total_matches,
            reserved_templates=max(0, settings.qsm_fingerprint_template_start),
            error_message=str(result.get("error_message")) if result.get("error_message") else None,
        )

    def identify(self, timeout: int = 45) -> FingerprintActionResponse:
        result = self.client.identify(timeout=timeout)
        if not result.get("ok"):
            return self._failure(result, "指纹确认未完成，请重新放置手指。")
        if not result.get("matched"):
            return FingerprintActionResponse(
                ok=False,
                status="unknown",
                message="该指纹尚未绑定服务对象，可改用面部确认或由管理员录入。",
                error_message="该指纹尚未绑定服务对象。",
            )
        template_id = self._int(result.get("id"))
        score = self._float(result.get("score"))
        if template_id is None:
            return FingerprintActionResponse(ok=False, status="invalid", message="指纹模块未返回模板编号。", error_message="指纹模块未返回模板编号。")
        user = self._user_for_template(template_id)
        if user is None:
            return FingerprintActionResponse(
                ok=False,
                status="unbound",
                template_id=template_id,
                score=score,
                message="识别到未绑定的板端指纹，请由管理员重新录入。",
                error_message="识别到未绑定的板端指纹。",
            )
        now = db.now_text()
        with db.connect() as conn:
            conn.execute(
                "UPDATE fingerprint_identities SET score=?, match_count=match_count+1, last_seen_at=? WHERE template_id=?",
                (score, now, template_id),
            )
            usage = conn.execute(
                "SELECT match_count, last_seen_at FROM fingerprint_identities WHERE template_id=?",
                (template_id,),
            ).fetchone()
        return FingerprintActionResponse(
            ok=True,
            status="matched",
            user=user,
            template_id=template_id,
            score=score,
            match_count=int(usage["match_count"]) if usage else 1,
            last_seen_at=str(usage["last_seen_at"]) if usage else now,
            message=f"指纹已确认：{user.name}",
        )

    def enroll_user(self, user_id: str, timeout: int = 45) -> FingerprintActionResponse:
        prepared = self._prepare_enrollment(user_id)
        if isinstance(prepared, FingerprintActionResponse):
            return prepared
        user, template_id = prepared
        result = self.client.enroll(template_id, timeout=timeout)
        if not result.get("ok") or str(result.get("event") or result.get("status")) not in {"enrolled", "complete"}:
            return self._failure(result, "指纹录入未完成，请按提示连续放置同一手指。", user=user, template_id=template_id)
        self._bind_identity(user_id, template_id)
        return FingerprintActionResponse(ok=True, status="enrolled", event="enrolled", user=user, template_id=template_id, message=f"{user.name}的指纹已录入。")

    def start_enrollment(self, user_id: str, timeout: int = 60) -> FingerprintActionResponse:
        prepared = self._prepare_enrollment(user_id)
        if isinstance(prepared, FingerprintActionResponse):
            return prepared
        user, template_id = prepared
        result = self.client.start_enrollment(template_id, timeout=timeout)
        if not result.get("ok"):
            return self._failure(result, "无法启动指纹录入。", user=user, template_id=template_id)
        job_id = str(result.get("job_id") or "").strip()
        if not job_id:
            return FingerprintActionResponse(
                ok=False,
                status="invalid",
                user=user,
                template_id=template_id,
                message="指纹模块未返回录入任务编号。",
                error_message="指纹模块未返回录入任务编号。",
            )
        event = str(result.get("event") or "place_finger_first")
        message = self._event_message(event)
        now = db.now_text()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fingerprint_enrollment_jobs(
                  job_id, service_user_id, template_id, status, event, message, created_at, updated_at
                ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (job_id, user_id, template_id, event, message, now, now),
            )
        return FingerprintActionResponse(
            ok=True,
            status="running",
            event=event,
            job_id=job_id,
            user=user,
            template_id=template_id,
            message=message,
        )

    def enrollment_progress(self, user_id: str, job_id: str) -> FingerprintActionResponse:
        user = self._get_user(user_id)
        if user is None:
            return FingerprintActionResponse(ok=False, status="not_found", message="服务对象不存在。", error_message="服务对象不存在。")
        db.init_db()
        with db.connect() as conn:
            job = conn.execute(
                "SELECT service_user_id, template_id, status, event, message FROM fingerprint_enrollment_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        if job is None or str(job["service_user_id"]) != user_id:
            return FingerprintActionResponse(ok=False, status="not_found", user=user, job_id=job_id, message="指纹录入任务不存在。", error_message="指纹录入任务不存在。")
        template_id = int(job["template_id"])
        if str(job["status"]) == "enrolled":
            return FingerprintActionResponse(
                ok=True,
                status="enrolled",
                event="enrolled",
                job_id=job_id,
                user=user,
                template_id=template_id,
                message=str(job["message"]),
            )
        result = self.client.enrollment_progress(job_id)
        event = str(result.get("event") or job["event"] or "running")
        status = str(result.get("status") or "running")
        if not result.get("ok") and status != "running":
            response = self._failure(result, "指纹录入未完成，请重新录入。", user=user, template_id=template_id, job_id=job_id, event=event)
            self._save_enrollment_job(job_id, response.status, event, response.message)
            return response
        if status in {"enrolled", "complete"} or event == "enrolled":
            self._bind_identity(user_id, template_id)
            message = f"{user.name}的指纹已录入。"
            self._save_enrollment_job(job_id, "enrolled", "enrolled", message)
            return FingerprintActionResponse(
                ok=True,
                status="enrolled",
                event="enrolled",
                job_id=job_id,
                user=user,
                template_id=template_id,
                message=message,
            )
        message = self._event_message(event)
        self._save_enrollment_job(job_id, "running", event, message)
        return FingerprintActionResponse(
            ok=True,
            status="running",
            event=event,
            job_id=job_id,
            user=user,
            template_id=template_id,
            message=message,
        )

    def delete_user(self, user_id: str) -> FingerprintActionResponse:
        user = self._get_user(user_id)
        db.init_db()
        with db.connect() as conn:
            row = conn.execute("SELECT template_id FROM fingerprint_identities WHERE service_user_id=?", (user_id,)).fetchone()
        if row is None:
            return FingerprintActionResponse(ok=True, status="not_enrolled", user=user, message="该服务对象没有已录入指纹。")
        template_id = int(row["template_id"])
        result = self.client.delete(template_id)
        if not result.get("ok"):
            return self._failure(result, "板端指纹模板删除失败。", user=user, template_id=template_id)
        with db.connect() as conn:
            conn.execute("DELETE FROM fingerprint_identities WHERE template_id=?", (template_id,))
        return FingerprintActionResponse(ok=True, status="deleted", user=user, template_id=template_id, message="指纹已删除。")

    def _prepare_enrollment(self, user_id: str) -> tuple[ServiceUser, int] | FingerprintActionResponse:
        user = self._get_user(user_id)
        if user is None:
            return FingerprintActionResponse(ok=False, status="not_found", message="服务对象不存在。", error_message="服务对象不存在。")
        db.init_db()
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT template_id FROM fingerprint_identities WHERE service_user_id=?",
                (user_id,),
            ).fetchone()
            used = {int(row["template_id"]) for row in conn.execute("SELECT template_id FROM fingerprint_identities")}
        template_id = int(existing["template_id"]) if existing else self._next_template_id(used)
        if template_id is None:
            return FingerprintActionResponse(ok=False, status="full", user=user, message="指纹模板空间已满。", error_message="指纹模板空间已满。")
        return user, template_id

    @staticmethod
    def _bind_identity(user_id: str, template_id: int) -> None:
        now = db.now_text()
        with db.connect() as conn:
            conn.execute("DELETE FROM fingerprint_identities WHERE template_id=? OR service_user_id=?", (template_id, user_id))
            conn.execute(
                "INSERT INTO fingerprint_identities(template_id, service_user_id, score, match_count, enrolled_at, last_seen_at) VALUES (?, ?, NULL, 0, ?, ?)",
                (template_id, user_id, now, now),
            )

    @staticmethod
    def _save_enrollment_job(job_id: str, status: str, event: str, message: str) -> None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE fingerprint_enrollment_jobs SET status=?, event=?, message=?, updated_at=? WHERE job_id=?",
                (status, event, message, db.now_text(), job_id),
            )

    @staticmethod
    def _event_message(event: str) -> str:
        return {
            "place_finger_first": "请将常用手指完整覆盖识别区域并保持不动。",
            "remove_finger": "首次采集完成，请将手指完全移开。",
            "finger_removed": "已检测到手指移开，请准备再次放置。",
            "place_same_finger_second": "请再次放置同一根手指并保持不动。",
            "enrolled": "指纹录入完成。",
        }.get(event, "正在采集指纹特征，请按屏幕提示操作。")

    @staticmethod
    def _next_template_id(used: set[int]) -> int | None:
        for template_id in range(max(0, settings.qsm_fingerprint_template_start), 300):
            if template_id not in used:
                return template_id
        return None

    @staticmethod
    def _get_user(user_id: str) -> ServiceUser | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute("SELECT id, name, age, profile, allergies, note, status FROM service_users WHERE id=?", (user_id,)).fetchone()
        return ServiceUser(**dict(row)) if row else None

    def _user_for_template(self, template_id: int) -> ServiceUser | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.name, u.age, u.profile, u.allergies, u.note, u.status
                FROM fingerprint_identities f JOIN service_users u ON u.id=f.service_user_id
                WHERE f.template_id=?
                """,
                (template_id,),
            ).fetchone()
        return ServiceUser(**dict(row)) if row else None

    @staticmethod
    def _failure(result: dict, fallback: str, **values) -> FingerprintActionResponse:
        code = str(result.get("error_message") or result.get("error") or "").strip()
        messages = {
            "finger_wait_timeout": "未检测到手指，请完整覆盖指纹窗口后重试。",
            "two_captures_not_match": "两次采集不是同一根手指，请重新录入。",
            "image_too_messy": "指纹图像不清晰，请擦拭手指和识别窗口后重试。",
            "feature_too_few": "采集到的指纹特征不足，请完整按住识别窗口。",
            "too_few_features": "采集到的指纹特征不足，请完整按住识别窗口。",
            "finger_removal_timeout": "首次采集后未检测到手指移开，请完全抬起手指后重新录入。",
            "busy": "已有指纹录入正在进行，请先完成当前录入。",
            "not_found": "未匹配到已录入指纹，可改用面部确认。",
        }
        message = messages.get(code, code or fallback)
        status = str(result.get("status") or "error")
        if code == "finger_wait_timeout":
            status = "timeout"
        return FingerprintActionResponse(ok=False, status=status, message=message, error_message=message, **values)

    @staticmethod
    def _int(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
