from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from ..config import DATA_DIR


class DeviceActionRecord(BaseModel):
    id: str
    created_at: str
    type: str
    title: str
    description: str
    target_user: str = "站点"
    status: str = "已记录"


class DeviceActionRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "device_action_records.json"

    def list_records(self) -> list[DeviceActionRecord]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, list):
            return []
        return [DeviceActionRecord(**item) for item in payload]

    def append(self, record: DeviceActionRecord) -> DeviceActionRecord:
        records = self.list_records()
        records.insert(0, record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump([item.model_dump() for item in records], file, ensure_ascii=False, indent=2)
        return record
