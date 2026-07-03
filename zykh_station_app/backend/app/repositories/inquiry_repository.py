from __future__ import annotations

import json
from pathlib import Path

from ..config import DATA_DIR
from ..schemas.inquiry import InquiryResult


class InquiryRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "inquiry_records.json"

    def list_records(self) -> list[InquiryResult]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, list):
            return []
        return [InquiryResult(**item) for item in payload]

    def get_by_id(self, inquiry_id: str) -> InquiryResult | None:
        return next((record for record in self.list_records() if record.inquiry_id == inquiry_id), None)

    def append(self, result: InquiryResult) -> InquiryResult:
        records = self.list_records()
        records.insert(0, result)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump([item.model_dump() for item in records], file, ensure_ascii=False, indent=2)
        return result
