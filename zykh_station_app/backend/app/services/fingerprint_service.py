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
        return FingerprintStatusResponse(
            ok=bool(result.get("ok")),
            status=str(result.get("status") or ("available" if result.get("ok") else "unavailable")),
            device=str(result.get("device")) if result.get("device") else None,
            count=int(result.get("count") or 0),
            capacity=int(result.get("capacity") or 300),
            bound_users=bound_users,
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
        with db.connect() as conn:
            conn.execute(
                "UPDATE fingerprint_identities SET score=?, last_seen_at=? WHERE template_id=?",
                (score, db.now_text(), template_id),
            )
        return FingerprintActionResponse(
            ok=True,
            status="matched",
            user=user,
            template_id=template_id,
            score=score,
            message=f"指纹已确认：{user.name}",
        )

    def enroll_user(self, user_id: str, timeout: int = 45) -> FingerprintActionResponse:
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
        if existing:
            self.client.delete(template_id)
        result = self.client.enroll(template_id, timeout=timeout)
        if not result.get("ok") or str(result.get("event") or result.get("status")) not in {"enrolled", "complete"}:
            return self._failure(result, "指纹录入未完成，请按提示连续放置同一手指。", user=user, template_id=template_id)
        now = db.now_text()
        with db.connect() as conn:
            conn.execute("DELETE FROM fingerprint_identities WHERE template_id=? OR service_user_id=?", (template_id, user_id))
            conn.execute(
                "INSERT INTO fingerprint_identities(template_id, service_user_id, score, enrolled_at, last_seen_at) VALUES (?, ?, NULL, ?, ?)",
                (template_id, user_id, now, now),
            )
        return FingerprintActionResponse(ok=True, status="enrolled", user=user, template_id=template_id, message=f"{user.name}的指纹已录入。")

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
        message = str(result.get("error_message") or result.get("error") or fallback)
        return FingerprintActionResponse(ok=False, status=str(result.get("status") or "error"), message=message, error_message=message, **values)

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
