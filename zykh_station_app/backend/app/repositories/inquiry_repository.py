from __future__ import annotations

import json
from uuid import uuid4

from .. import db
from ..schemas.inquiry import InquiryMessage, InquiryResult, InquirySessionResponse


_LEGACY_TECHNICAL_REPLY_MARKERS = (
    "智能问询当前暂不可用",
    "本次不会生成用药候选",
    "连接有些不稳定",
    "分析连接",
    "规则兜底",
    "本地兜底",
)
_LEGACY_RETRY_REPLY = "这一轮没有完整整理好，请重新开始问询，并重新说明现在最不舒服的地方。"


def _present_legacy_reply(content: str, source: str) -> tuple[str, str]:
    if any(marker in content for marker in _LEGACY_TECHNICAL_REPLY_MARKERS):
        return _LEGACY_RETRY_REPLY, "assistant"
    return content, source


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

    def save_session(self, session: InquirySessionResponse) -> InquirySessionResponse:
        db.init_db()
        primary = session.primary_candidate.model_dump() if session.primary_candidate else None
        alternative = session.alternative_candidate.model_dump() if session.alternative_candidate else None
        treatment_options = [option.model_dump() for option in session.treatment_options]
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO inquiry_sessions(
                  session_id, user_id, user_name, user_age, user_profile, user_allergies,
                  stage, reply, source, reasoning_summary, model_action_intent, action_reason,
                  extracted_json, vitals_json, risk_level,
                  risk_reasons_json, next_action, primary_candidate_json,
                  alternative_candidate_json, treatment_options_json, can_view_medicines,
                  selected_option_id, action_status, action_message,
                  action_progress_index, action_total_items, action_items_json,
                  title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  user_id=excluded.user_id,
                  user_name=excluded.user_name,
                  user_age=excluded.user_age,
                  user_profile=excluded.user_profile,
                  user_allergies=excluded.user_allergies,
                  stage=excluded.stage,
                  reply=excluded.reply,
                  source=excluded.source,
                  reasoning_summary=excluded.reasoning_summary,
                  model_action_intent=excluded.model_action_intent,
                  action_reason=excluded.action_reason,
                  extracted_json=excluded.extracted_json,
                  vitals_json=excluded.vitals_json,
                  risk_level=excluded.risk_level,
                  risk_reasons_json=excluded.risk_reasons_json,
                  next_action=excluded.next_action,
                  primary_candidate_json=excluded.primary_candidate_json,
                  alternative_candidate_json=excluded.alternative_candidate_json,
                  treatment_options_json=excluded.treatment_options_json,
                  can_view_medicines=excluded.can_view_medicines,
                  selected_option_id=excluded.selected_option_id,
                  action_status=excluded.action_status,
                  action_message=excluded.action_message,
                  action_progress_index=excluded.action_progress_index,
                  action_total_items=excluded.action_total_items,
                  action_items_json=excluded.action_items_json,
                  title=excluded.title,
                  updated_at=excluded.updated_at
                """,
                (
                    session.session_id,
                    session.user_id,
                    session.user_name,
                    session.user_age,
                    session.user_profile,
                    session.user_allergies,
                    session.stage,
                    session.reply,
                    session.source,
                    session.reasoning_summary,
                    session.model_action_intent,
                    session.action_reason,
                    json.dumps(session.extracted_information.model_dump(), ensure_ascii=False),
                    json.dumps(session.vitals, ensure_ascii=False) if session.vitals else "",
                    session.risk_level or "",
                    json.dumps(session.risk_reasons, ensure_ascii=False),
                    session.next_action,
                    json.dumps(primary, ensure_ascii=False) if primary else "",
                    json.dumps(alternative, ensure_ascii=False) if alternative else "",
                    json.dumps(treatment_options, ensure_ascii=False),
                    int(session.can_view_medicines),
                    session.selected_option_id,
                    session.action_status,
                    session.action_message,
                    session.action_progress_index,
                    session.action_total_items,
                    json.dumps(session.action_items, ensure_ascii=False),
                    session.title,
                    session.created_at,
                    session.updated_at,
                ),
            )
        return session

    def append_message(self, session_id: str, role: str, content: str, source: str = "") -> InquiryMessage:
        message = InquiryMessage(
            id=f"message-{uuid4().hex[:14]}",
            role=role,
            content=content,
            source=source,
            created_at=db.now_text(),
        )
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO inquiry_messages(id, session_id, role, content, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message.id, session_id, message.role, message.content, message.source, message.created_at),
            )
        return message

    def get_session(self, session_id: str) -> InquirySessionResponse | None:
        db.init_db()
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM inquiry_sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                return None
            message_rows = conn.execute(
                """
                SELECT id, role, content, source, created_at
                FROM inquiry_messages
                WHERE session_id=?
                ORDER BY rowid
                """,
                (session_id,),
            ).fetchall()
        values = dict(row)
        reply, source = _present_legacy_reply(values["reply"], values["source"])
        messages = []
        for raw_message in message_rows:
            message = dict(raw_message)
            if message["role"] == "assistant":
                message["content"], message["source"] = _present_legacy_reply(
                    message["content"],
                    message["source"],
                )
            messages.append(InquiryMessage(**message))
        return InquirySessionResponse(
            session_id=values["session_id"],
            user_id=values["user_id"],
            user_name=values["user_name"],
            user_age=values["user_age"],
            user_profile=values["user_profile"],
            user_allergies=values["user_allergies"],
            stage=values["stage"],
            reply=reply,
            source=source,
            reasoning_summary=values.get("reasoning_summary", ""),
            model_action_intent=values.get("model_action_intent", "ask") or "ask",
            action_reason=values.get("action_reason", ""),
            extracted_information=json.loads(values["extracted_json"] or "{}"),
            vitals=json.loads(values["vitals_json"]) if values["vitals_json"] else None,
            risk_level=values["risk_level"] or None,
            risk_reasons=json.loads(values["risk_reasons_json"] or "[]"),
            next_action=values["next_action"],
            primary_candidate=json.loads(values["primary_candidate_json"])
            if values["primary_candidate_json"]
            else None,
            alternative_candidate=json.loads(values["alternative_candidate_json"])
            if values["alternative_candidate_json"]
            else None,
            treatment_options=json.loads(values.get("treatment_options_json") or "[]"),
            can_view_medicines=bool(values["can_view_medicines"]),
            selected_option_id=values.get("selected_option_id", ""),
            action_status=values.get("action_status", "idle") or "idle",
            action_message=values.get("action_message", ""),
            action_progress_index=int(values.get("action_progress_index", 0) or 0),
            action_total_items=int(values.get("action_total_items", 0) or 0),
            action_items=json.loads(values.get("action_items_json") or "[]"),
            messages=messages,
            title=values["title"],
            created_at=values["created_at"],
            updated_at=values["updated_at"],
        )

    def list_sessions(self, limit: int = 20) -> list[InquirySessionResponse]:
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM inquiry_sessions ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [session for row in rows if (session := self.get_session(str(row["session_id"]))) is not None]

    def list_user_sessions(
        self,
        user_id: str,
        *,
        exclude_session_id: str = "",
        limit: int = 8,
    ) -> list[InquirySessionResponse]:
        if not user_id:
            return []
        db.init_db()
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id
                FROM inquiry_sessions
                WHERE user_id=? AND session_id<>? AND risk_level<>''
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, exclude_session_id, max(1, min(limit, 30))),
            ).fetchall()
        return [session for row in rows if (session := self.get_session(str(row["session_id"]))) is not None]
