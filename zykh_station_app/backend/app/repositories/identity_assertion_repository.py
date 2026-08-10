from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from .. import db
from ..schemas.manual_medication_access import IdentityAssertion


_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class IdentityAssertionRepository:
    """Short-lived proof that a board identity flow matched one registered user."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or datetime.now

    def issue(
        self,
        *,
        service_user_id: str,
        verification_method: str,
        verification_score: float | None = None,
        ttl_seconds: int = 120,
    ) -> IdentityAssertion:
        db.init_db()
        method = str(verification_method or "").strip().lower()
        if method not in {"face", "fingerprint"}:
            raise ValueError("身份断言只支持面部或指纹确认。")
        now = self._clock()
        assertion = IdentityAssertion(
            assertion_id=f"identity-assertion-{uuid4().hex}",
            service_user_id=service_user_id,
            verification_method=method,
            verification_score=verification_score,
            created_at=now.strftime(_TIMESTAMP_FORMAT),
            expires_at=(now + timedelta(seconds=max(1, ttl_seconds))).strftime(_TIMESTAMP_FORMAT),
        )
        with db.connect() as conn:
            user = conn.execute(
                "SELECT id FROM service_users WHERE id=? AND archived=0",
                (service_user_id,),
            ).fetchone()
            if user is None:
                raise ValueError("不能为未登记或已归档人物签发身份断言。")
            conn.execute(
                """
                INSERT INTO identity_assertions(
                  assertion_id, service_user_id, verification_method,
                  verification_score, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    assertion.assertion_id,
                    assertion.service_user_id,
                    assertion.verification_method,
                    assertion.verification_score,
                    assertion.created_at,
                    assertion.expires_at,
                ),
            )
        return assertion
    def get_valid(
        self,
        assertion_id: str,
        *,
        service_user_id: str,
        verification_method: str,
    ) -> IdentityAssertion | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT assertion_id, service_user_id, verification_method,
                       verification_score, created_at, expires_at
                FROM identity_assertions
                WHERE assertion_id=?
                """,
                (assertion_id,),
            ).fetchone()
        if row is None:
            return None
        assertion = IdentityAssertion(**dict(row))
        if assertion.service_user_id != service_user_id:
            return None
        if assertion.verification_method != str(verification_method or "").strip().lower():
            return None
        try:
            expires_at = datetime.strptime(assertion.expires_at, _TIMESTAMP_FORMAT)
        except ValueError:
            return None
        if expires_at <= self._clock():
            return None
        return assertion
