from __future__ import annotations

import json

from .. import db
from ..schemas.inquiry import InquiryResult


class InquiryRepository:
    def list_records(self) -> list[InquiryResult]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM inquiry_records
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [InquiryResult(**json.loads(row["payload_json"])) for row in rows]

    def get_by_id(self, inquiry_id: str) -> InquiryResult | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM inquiry_records WHERE inquiry_id=?",
                (inquiry_id,),
            ).fetchone()
        return InquiryResult(**json.loads(row["payload_json"])) if row else None

    def append(self, result: InquiryResult) -> InquiryResult:
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO inquiry_records(inquiry_id, payload_json, created_at)
                VALUES (?, ?, ?)
                """,
                (result.inquiry_id, json.dumps(result.model_dump(), ensure_ascii=False), result.created_at),
            )
        return result
