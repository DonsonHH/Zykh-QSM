from __future__ import annotations

import hashlib
import re
from datetime import datetime
from uuid import uuid4

from .. import db
from ..schemas.identity import FaceEnrollmentResponse, IdentityResponse, IdentityStatusResponse
from ..schemas.records import ServiceUser
from .qsm_face_client import QsmFaceClient


class IdentityService:
    def __init__(self, face_client: QsmFaceClient | None = None) -> None:
        self.face_client = face_client or QsmFaceClient()

    def resolve(self) -> IdentityResponse:
        result = self.face_client.identify()
        status = str(result.get("status") or "unavailable")
        confidence = self._confidence(result.get("confidence"))
        if status == "matched" and result.get("subject"):
            subject = str(result["subject"])
            user = self._user_for_subject(subject)
            if user is None:
                user = self._recover_direct_subject(subject)
            if user is None:
                message = "识别到尚未绑定的历史人脸，请由管理员为现有服务对象重新录入人脸。"
                return IdentityResponse(
                    ok=False,
                    status="unbound",
                    subject=subject,
                    confidence=confidence,
                    message=message,
                    error_message=message,
                )
            self._touch(subject, confidence)
            return IdentityResponse(
                ok=True,
                status="matched",
                user=user,
                subject=subject,
                confidence=confidence,
                message=f"已确认使用人：{user.name}",
            )

        if status == "unknown":
            message = "未匹配到已录入身份，请正对摄像头重试，或由管理员先建立服务对象并录入人脸。"
            return IdentityResponse(
                ok=False,
                status="unknown",
                confidence=confidence,
                message=message,
                error_message=message,
            )

        message = str(result.get("error_message") or "暂时无法确认使用人，请正对摄像头后重试。")
        return IdentityResponse(
            ok=False,
            status=status,
            confidence=confidence,
            message=message,
            error_message=message,
        )

    def enroll_user(self, user_id: str, samples: int = 18) -> FaceEnrollmentResponse:
        user = self._get_user(user_id)
        if user is None:
            return FaceEnrollmentResponse(
                ok=False,
                status="not_found",
                message="服务对象不存在。",
                error_message="服务对象不存在。",
            )
        subject = self._subject_for_user(user.id)
        result = self.face_client.enroll(subject, samples=samples)
        if not result.get("ok"):
            message = str(result.get("error_message") or "人脸录入未完成，请保持正对摄像头后重试。")
            return FaceEnrollmentResponse(
                ok=False,
                status=str(result.get("status") or "enroll_failed"),
                user=user,
                subject=subject,
                samples=self._int_or_none(result.get("samples")),
                message=message,
                error_message=message,
            )
        self._bind(subject, user.id, None)
        return FaceEnrollmentResponse(
            ok=True,
            status="enrolled",
            user=user,
            subject=subject,
            samples=self._int_or_none(result.get("samples")),
            message=f"{user.name}的人脸已录入。",
        )

    def verify_for_dispense(self, samples: int = 18) -> IdentityResponse:
        resolved = self.resolve()
        if resolved.ok and resolved.user:
            return resolved
        if resolved.status != "unknown":
            return resolved

        user = self._create_guest_user()
        subject = self._subject_for_user(user.id)
        result = self.face_client.enroll(subject, samples=samples)
        if not result.get("ok"):
            with db.connect() as conn:
                conn.execute("DELETE FROM service_users WHERE id=?", (user.id,))
            message = str(result.get("error_message") or "面部信息留存未完成，请保持正对摄像头后重试。")
            return IdentityResponse(
                ok=False,
                status=str(result.get("status") or "enroll_failed"),
                message=message,
                error_message=message,
            )
        self._bind(subject, user.id, None)
        return IdentityResponse(
            ok=True,
            status="created",
            user=user,
            subject=subject,
            message=f"已建立本地访客记录：{user.name}",
            new_guest=True,
        )

    def status(self) -> IdentityStatusResponse:
        result = self.face_client.status()
        db.init_db()
        with db.connect() as conn:
            count = int(conn.execute("SELECT COUNT(*) AS count FROM face_identities").fetchone()["count"])
        return IdentityStatusResponse(
            ok=bool(result.get("ok")),
            status=str(result.get("status") or "unavailable"),
            camera_available=bool(result.get("camera_available")),
            runtime_available=bool(result.get("runtime_available")),
            enrolled_samples=int(result.get("enrolled_samples") or 0),
            bound_users=count,
            error_message=str(result.get("error_message")) if result.get("error_message") else None,
        )

    @staticmethod
    def _subject_for_user(user_id: str) -> str:
        direct = f"profile:{user_id}"
        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,63}", direct):
            return direct
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        return f"profile:{digest}"

    def _recover_direct_subject(self, subject: str) -> ServiceUser | None:
        if not subject.startswith("profile:"):
            return None
        user = self._get_user(subject.split(":", 1)[1])
        if user:
            self._bind(subject, user.id, None)
        return user

    @staticmethod
    def _create_guest_user() -> ServiceUser:
        db.init_db()
        now = datetime.now()
        user_id = f"guest-{now.strftime('%Y%m%d-%H%M')}-{uuid4().hex[:5]}"
        name = f"访客 {now.strftime('%m%d-%H%M')}"
        user = ServiceUser(
            id=user_id,
            name=name,
            age=0,
            profile="未登记",
            allergies="",
            note="面部确认建立，可在设置中补充资料",
            status="访客",
        )
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO service_users(id, name, age, profile, allergies, note, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user.id, user.name, user.age, user.profile, user.allergies, user.note, user.status),
            )
        return user

    def _user_for_subject(self, subject: str) -> ServiceUser | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.name, u.age, u.profile, u.allergies, u.note, u.status
                FROM face_identities f
                JOIN service_users u ON u.id=f.service_user_id
                WHERE f.subject=?
                """,
                (subject,),
            ).fetchone()
        return ServiceUser(**dict(row)) if row else None

    @staticmethod
    def _get_user(user_id: str) -> ServiceUser | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT id, name, age, profile, allergies, note, status FROM service_users WHERE id=?",
                (user_id,),
            ).fetchone()
        return ServiceUser(**dict(row)) if row else None

    @staticmethod
    def _bind(subject: str, user_id: str, confidence: float | None) -> None:
        now = db.now_text()
        db.init_db()
        with db.connect() as conn:
            conn.execute("DELETE FROM face_identities WHERE subject=? OR service_user_id=?", (subject, user_id))
            conn.execute(
                """
                INSERT INTO face_identities(subject, service_user_id, confidence, enrolled_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (subject, user_id, confidence, now, now),
            )

    @staticmethod
    def _touch(subject: str, confidence: float | None) -> None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE face_identities SET confidence=?, last_seen_at=? WHERE subject=?",
                (confidence, db.now_text(), subject),
            )

    @staticmethod
    def _confidence(value: object) -> float | None:
        try:
            parsed = float(value)
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
