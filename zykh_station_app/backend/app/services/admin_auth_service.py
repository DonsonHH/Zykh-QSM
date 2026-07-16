from __future__ import annotations

import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import settings


class AdminAuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AdminSession:
    token: str
    expires_at: datetime


class AdminAuthService:
    _lock = threading.Lock()
    _sessions: dict[str, float] = {}
    _failures: dict[str, list[float]] = {}
    _failure_window_seconds = 60.0
    _failure_limit = 5

    def create_session(self, pin: str, client_id: str) -> AdminSession:
        client_key = client_id or "unknown"
        now_mono = time.monotonic()
        with self._lock:
            failures = [
                value
                for value in self._failures.get(client_key, [])
                if now_mono - value < self._failure_window_seconds
            ]
            self._failures[client_key] = failures
            if len(failures) >= self._failure_limit:
                raise AdminAuthError("尝试次数过多，请一分钟后再试。", status_code=429)

        if not hmac.compare_digest(str(pin), settings.admin_debug_pin):
            with self._lock:
                self._failures.setdefault(client_key, []).append(now_mono)
            raise AdminAuthError("管理员口令不正确。")

        ttl_seconds = max(5, settings.admin_session_minutes) * 60
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now().astimezone() + timedelta(seconds=ttl_seconds)
        with self._lock:
            self._failures.pop(client_key, None)
            self._sessions[token] = now_mono + ttl_seconds
            self._purge_locked(now_mono)
        return AdminSession(token=token, expires_at=expires_at)

    def verify(self, token: str) -> None:
        now_mono = time.monotonic()
        with self._lock:
            self._purge_locked(now_mono)
            expires_at = self._sessions.get(token)
            if expires_at is None or expires_at <= now_mono:
                raise AdminAuthError("管理员会话已失效，请重新验证。")

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._sessions.clear()
            cls._failures.clear()

    @classmethod
    def _purge_locked(cls, now_mono: float) -> None:
        expired = [token for token, expires_at in cls._sessions.items() if expires_at <= now_mono]
        for token in expired:
            cls._sessions.pop(token, None)
