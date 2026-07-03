from __future__ import annotations

import json
from pathlib import Path

from ..config import DATA_DIR
from ..schemas.dispense import DispenseRecord


class DispenseRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "dispense_records.json"

    def list_records(self) -> list[DispenseRecord]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, list):
            return []
        return [DispenseRecord(**item) for item in payload]

    def append(self, record: DispenseRecord) -> DispenseRecord:
        records = self.list_records()
        records.insert(0, record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump([item.model_dump() for item in records], file, ensure_ascii=False, indent=2)
        return record
