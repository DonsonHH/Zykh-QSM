from __future__ import annotations

import json
from pathlib import Path

from ..config import DATA_DIR
from ..schemas.sync import SyncStatus


DEFAULT_SYNC_STATUS = SyncStatus(
    sync_status="待同步",
    pending_count=12,
    last_sync_at="未同步",
    network_mode="弱网",
)


class SyncRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "sync_state.json"

    def get_status(self) -> SyncStatus:
        if not self.path.exists():
            return DEFAULT_SYNC_STATUS
        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            return DEFAULT_SYNC_STATUS
        return SyncStatus(**payload)

    def save_status(self, status: SyncStatus) -> SyncStatus:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(status.model_dump(), file, ensure_ascii=False, indent=2)
        return status
