from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .records_service import RecordsService


CAREGIVER_READ_PERMISSIONS = (
    "READ_SAFETY",
    "READ_INQUIRY",
    "READ_PLAN",
    "READ_PROFILE",
    "READ_RECORD",
    "READ_VITALS",
    "READ_MEDICINE",
    # This capability is narrowed again by the CloudBase command-type policy:
    # paired caregivers may only request reminders, beeps and vitals.
    "CREATE_COMMAND",
)


@dataclass(frozen=True)
class PairingCodeIssueRequest:
    service_user_ids: tuple[str, ...]
    ttl_minutes: int = 10


@dataclass(frozen=True)
class PairingCodePlaintextOnce:
    pairing_code: str
    expires_at: str
    ttl_seconds: int
    service_user_ids: tuple[str, ...]


class PairingCodeIssueError(RuntimeError):
    pass


class PairingCodeIssuer:
    """Issue one-time caregiver pairing codes through one narrow interface."""

    def __init__(
        self,
        *,
        publish: Callable[[dict[str, object]], object] | None = None,
        token_factory: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._publish = publish or self._publish_to_cloud
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._now = now or (lambda: datetime.now(timezone.utc))

    def issue(self, request: PairingCodeIssueRequest) -> PairingCodePlaintextOnce:
        if not 5 <= int(request.ttl_minutes) <= 15:
            raise PairingCodeIssueError("配对码有效期必须为 5 到 15 分钟。")
        scopes = tuple(dict.fromkeys(str(item or "").strip() for item in request.service_user_ids))
        if not scopes or any(not item for item in scopes):
            raise PairingCodeIssueError("请至少选择一位服务对象。")
        active_users = {item.id: item for item in RecordsService().list_service_users()}
        if any(item not in active_users for item in scopes):
            raise PairingCodeIssueError("所选服务对象不存在或已停用。")
        scope_generations = {
            item: str(active_users[item].persona_generation or "").strip()
            for item in scopes
        }
        if any(not generation for generation in scope_generations.values()):
            raise PairingCodeIssueError("所选服务对象缺少人物代次，无法安全配对。")

        pairing_code = str(self._token_factory() or "").strip()
        if not 16 <= len(pairing_code) <= 256:
            raise PairingCodeIssueError("无法生成安全的配对码，请重试。")
        payload: dict[str, object] = {
            "codeHash": hashlib.sha256(pairing_code.encode("utf-8")).hexdigest(),
            "serviceUserScopes": list(scopes),
            "serviceUserGenerations": scope_generations,
            "ttlSeconds": request.ttl_minutes * 60,
        }
        published = self._publish(payload)
        if not isinstance(published, dict):
            raise PairingCodeIssueError("云端未确认配对码授权对象，请重试。")
        published_scopes = tuple(
            dict.fromkeys(
                str(item or "").strip()
                for item in (published.get("serviceUserScopes") or [])
                if str(item or "").strip()
            )
        )
        if published_scopes != scopes:
            raise PairingCodeIssueError("云端返回的授权对象不一致，请重新生成。")
        raw_published_generations = published.get("serviceUserGenerations")
        if not isinstance(raw_published_generations, dict):
            raise PairingCodeIssueError("云端未确认人物代次，请重新生成。")
        published_generations = {
            str(key or "").strip(): str(value or "").strip()
            for key, value in raw_published_generations.items()
            if str(key or "").strip()
        }
        if published_generations != scope_generations:
            raise PairingCodeIssueError("云端返回的人物代次不一致，请重新生成。")
        published_permissions = tuple(
            dict.fromkeys(
                str(item or "").strip().upper()
                for item in (published.get("permissions") or [])
                if str(item or "").strip()
            )
        )
        if (
            str(published.get("role") or "").strip().upper() != "CAREGIVER"
            or str(published.get("status") or "").strip().upper() != "UNUSED"
            or len(published_permissions) != len(CAREGIVER_READ_PERMISSIONS)
            or set(published_permissions) != set(CAREGIVER_READ_PERMISSIONS)
        ):
            raise PairingCodeIssueError("云端返回的家属权限不符合最小协同授权要求。")
        expires_at = str(published.get("expiresAt", "")).strip()
        if not expires_at:
            raise PairingCodeIssueError("云端未确认配对码有效期，请重试。")
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            current = self._now()
            if expires.tzinfo is None or current.tzinfo is None:
                raise ValueError("timezone required")
            remaining_seconds = (expires - current).total_seconds()
        except (TypeError, ValueError):
            raise PairingCodeIssueError("云端返回的配对码有效期无效，请重试。")
        expected_seconds = request.ttl_minutes * 60
        if not expected_seconds - 60 <= remaining_seconds <= expected_seconds + 60:
            raise PairingCodeIssueError("云端返回的配对码有效期与请求不一致。")
        return PairingCodePlaintextOnce(
            pairing_code=pairing_code,
            expires_at=expires_at,
            ttl_seconds=request.ttl_minutes * 60,
            service_user_ids=published_scopes,
        )

    @staticmethod
    def _publish_to_cloud(payload: dict[str, object]) -> object:
        from .cloud_sync_service import cloud_sync_worker

        return cloud_sync_worker.issue_pairing_code_hash(payload)
