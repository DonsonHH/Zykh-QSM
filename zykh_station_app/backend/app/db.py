from __future__ import annotations

import json
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .config import settings


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path or settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_records (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              actor TEXT NOT NULL,
              action TEXT NOT NULL,
              target TEXT NOT NULL,
              result TEXT NOT NULL,
              detail TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medicines (
              id TEXT PRIMARY KEY,
              slot TEXT NOT NULL,
              hardware_slot INTEGER NOT NULL,
              barcode TEXT DEFAULT '',
              manufacturer TEXT DEFAULT '',
              name TEXT NOT NULL,
              category TEXT NOT NULL,
              spec TEXT NOT NULL DEFAULT '',
              trace_code TEXT NOT NULL DEFAULT '',
              tags_json TEXT NOT NULL,
              contraindications_json TEXT NOT NULL,
              stock INTEGER NOT NULL,
              low_stock_line INTEGER NOT NULL DEFAULT 1,
              unit TEXT NOT NULL,
              expire_date TEXT NOT NULL,
              image_hint TEXT NOT NULL,
              is_otc INTEGER NOT NULL,
              is_emergency INTEGER NOT NULL,
              safety_note TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "medicines", "manufacturer", "TEXT DEFAULT ''")
        _ensure_column(conn, "medicines", "spec", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicines", "trace_code", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicines", "low_stock_line", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "medicines", "aliases_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "medicines", "active_ingredients_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "medicines", "structured_contraindications_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "medicines", "indications", "TEXT DEFAULT ''")
        _ensure_column(conn, "medicines", "dosage", "TEXT DEFAULT ''")
        _ensure_column(conn, "medicines", "guidance_source", "TEXT DEFAULT 'pending'")
        _ensure_column(conn, "medicines", "guidance_review_required", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "medicines", "package_verified", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "medicines", "guidance_updated_at", "TEXT DEFAULT ''")
        _ensure_column(conn, "medicines", "safety_review_status", "TEXT NOT NULL DEFAULT 'draft'")
        _ensure_column(conn, "medicines", "safety_reviewed_by", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicines", "safety_reviewed_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicines", "inventory_state", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicines", "inventory_confirmed_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicines", "last_inventory_request_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicines", "inventory_revision", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(
            conn,
            "medicines",
            "last_inventory_dispense_record_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        conn.execute(
            """
            UPDATE medicines
            SET inventory_state=CASE WHEN stock > 0 THEN 'AVAILABLE' ELSE 'DEPLETED' END
            WHERE inventory_state NOT IN ('AVAILABLE', 'DEPLETED', 'UNKNOWN')
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medicine_inventory_confirmations (
              request_id TEXT PRIMARY KEY,
              request_payload_digest TEXT NOT NULL,
              medicine_id TEXT NOT NULL,
              dispense_record_id TEXT NOT NULL UNIQUE,
              observation TEXT NOT NULL,
              inventory_state TEXT NOT NULL,
              stock_after INTEGER NOT NULL,
              confirmed_at TEXT NOT NULL,
              FOREIGN KEY(medicine_id) REFERENCES medicines(id),
              FOREIGN KEY(dispense_record_id) REFERENCES dispense_records(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approved_medicine_combinations (
              combination_id TEXT PRIMARY KEY,
              label TEXT NOT NULL,
              medicine_ids_json TEXT NOT NULL,
              member_identity_fingerprints_json TEXT NOT NULL DEFAULT '{}',
              clinical_policy_version TEXT NOT NULL DEFAULT '',
              applicability_json TEXT NOT NULL DEFAULT '{}',
              member_review_fingerprints_json TEXT NOT NULL DEFAULT '{}',
              reviewed_usage_json TEXT NOT NULL DEFAULT '{}',
              evidence_refs_json TEXT NOT NULL DEFAULT '[]',
              provenance TEXT NOT NULL DEFAULT '',
              review_note TEXT NOT NULL DEFAULT '',
              review_status TEXT NOT NULL DEFAULT 'draft',
              reviewed_by TEXT NOT NULL DEFAULT '',
              reviewed_at TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "member_identity_fingerprints_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "clinical_policy_version",
            "TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "applicability_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "member_review_fingerprints_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "reviewed_usage_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "evidence_refs_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "provenance",
            "TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "approved_medicine_combinations",
            "review_note",
            "TEXT NOT NULL DEFAULT ''",
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medicine_ingredient_conflicts (
              left_ingredient TEXT NOT NULL,
              right_ingredient TEXT NOT NULL,
              disposition TEXT NOT NULL DEFAULT 'block',
              message TEXT NOT NULL DEFAULT '',
              review_status TEXT NOT NULL DEFAULT 'draft',
              reviewed_by TEXT NOT NULL DEFAULT '',
              reviewed_at TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL,
              PRIMARY KEY(left_ingredient, right_ingredient)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispense_records (
              id TEXT PRIMARY KEY,
              medicine_id TEXT NOT NULL,
              medicine_name TEXT NOT NULL,
              slot TEXT NOT NULL,
              hardware_slot INTEGER NOT NULL,
              quantity INTEGER NOT NULL,
              unit TEXT NOT NULL,
              reason TEXT NOT NULL,
              dry_run INTEGER NOT NULL,
              message TEXT NOT NULL,
              qsm_ok INTEGER NOT NULL DEFAULT 0,
              qsm_detail TEXT DEFAULT '',
              created_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "dispense_records", "target_user_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "dispense_records", "target_user_name", "TEXT NOT NULL DEFAULT '家庭成员'")
        _ensure_column(conn, "dispense_records", "verification_method", "TEXT NOT NULL DEFAULT 'manual'")
        _ensure_column(conn, "dispense_records", "verification_score", "REAL")
        _ensure_column(conn, "dispense_records", "target_user_type", "TEXT NOT NULL DEFAULT 'registered'")
        _ensure_column(conn, "dispense_records", "today_plan_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "dispense_records", "persona_generation", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispense_identity_archives (
              id TEXT PRIMARY KEY,
              dispense_record_id TEXT NOT NULL UNIQUE,
              target_user_name TEXT NOT NULL,
              medicine_name TEXT NOT NULL,
              captured_at TEXT NOT NULL,
              image_path TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              error_message TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_action_records (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              target_user TEXT NOT NULL,
              status TEXT NOT NULL,
              sync_status TEXT NOT NULL DEFAULT '待同步'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inquiry_records (
              inquiry_id TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inquiry_sessions (
              session_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL DEFAULT '',
              persona_generation TEXT NOT NULL DEFAULT '',
              user_name TEXT NOT NULL,
              user_age INTEGER NOT NULL DEFAULT 0,
              user_profile TEXT NOT NULL DEFAULT '',
              user_allergies TEXT NOT NULL DEFAULT '',
              stage TEXT NOT NULL,
              reply TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'rules_fallback',
              extracted_json TEXT NOT NULL DEFAULT '{}',
              vitals_json TEXT NOT NULL DEFAULT '',
              risk_level TEXT NOT NULL DEFAULT '',
              risk_reasons_json TEXT NOT NULL DEFAULT '[]',
              next_action TEXT NOT NULL,
              primary_candidate_json TEXT NOT NULL DEFAULT '',
              alternative_candidate_json TEXT NOT NULL DEFAULT '',
              can_view_medicines INTEGER NOT NULL DEFAULT 0,
              title TEXT NOT NULL DEFAULT '新问询',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inquiry_messages (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES inquiry_sessions(session_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS inquiry_messages_session_idx ON inquiry_messages(session_id, created_at, id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inquiry_guest_archives (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL UNIQUE,
              guest_name TEXT NOT NULL,
              captured_at TEXT NOT NULL,
              image_path TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              error_message TEXT NOT NULL DEFAULT '',
              FOREIGN KEY(session_id) REFERENCES inquiry_sessions(session_id)
            )
            """
        )
        _ensure_column(conn, "inquiry_sessions", "persona_generation", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "inquiry_sessions", "reasoning_summary", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "inquiry_sessions", "model_action_intent", "TEXT NOT NULL DEFAULT 'ask'")
        _ensure_column(conn, "inquiry_sessions", "action_reason", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "inquiry_sessions", "treatment_options_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "inquiry_sessions", "selected_option_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "inquiry_sessions", "action_status", "TEXT NOT NULL DEFAULT 'idle'")
        _ensure_column(conn, "inquiry_sessions", "action_message", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "inquiry_sessions", "action_progress_index", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "inquiry_sessions", "action_total_items", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "inquiry_sessions", "action_items_json", "TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vitals_records (
              id TEXT PRIMARY KEY,
              temperature REAL,
              heart_rate INTEGER,
              spo2 INTEGER,
              status TEXT NOT NULL,
              source TEXT NOT NULL,
              error_message TEXT DEFAULT '',
              measured_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "vitals_records", "systolic_pressure", "INTEGER")
        _ensure_column(conn, "vitals_records", "diastolic_pressure", "INTEGER")
        _ensure_column(conn, "vitals_records", "respiratory_rate", "INTEGER")
        _ensure_column(conn, "vitals_records", "microcirculation", "INTEGER")
        _ensure_column(conn, "vitals_records", "fatigue", "INTEGER")
        _ensure_column(conn, "vitals_records", "rr_interval", "INTEGER")
        _ensure_column(conn, "vitals_records", "hrv_sdnn", "INTEGER")
        _ensure_column(conn, "vitals_records", "hrv_rmssd", "INTEGER")
        _ensure_column(conn, "vitals_records", "body_temperature", "REAL")
        _ensure_column(conn, "vitals_records", "ambient_temperature", "REAL")
        _ensure_column(conn, "vitals_records", "sensor_model", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "vitals_records", "source_route", "TEXT NOT NULL DEFAULT 'HOME'")
        _ensure_column(conn, "vitals_records", "inquiry_session_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "vitals_records", "attribution_source", "TEXT NOT NULL DEFAULT 'UNREGISTERED'")
        _ensure_column(conn, "vitals_records", "service_user_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "vitals_records", "service_user_name_snapshot", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "vitals_records", "persona_generation", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "vitals_records", "temperature_source", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "vitals_records", "heart_rate_source", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "vitals_records", "spo2_source", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_vitals_records (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL UNIQUE,
              temperature REAL NOT NULL,
              heart_rate INTEGER NOT NULL,
              spo2 INTEGER NOT NULL,
              measured_at TEXT NOT NULL,
              source_route TEXT NOT NULL DEFAULT 'HOME',
              inquiry_session_id TEXT NOT NULL DEFAULT '',
              service_user_id TEXT NOT NULL DEFAULT '',
              persona_generation TEXT NOT NULL DEFAULT '',
              temperature_source TEXT NOT NULL DEFAULT '',
              heart_rate_source TEXT NOT NULL DEFAULT '',
              spo2_source TEXT NOT NULL DEFAULT '',
              demo_fallback_reason TEXT NOT NULL DEFAULT ''
            )
            """
        )
        _ensure_column(
            conn,
            "demo_vitals_records",
            "demo_fallback_reason",
            "TEXT NOT NULL DEFAULT ''",
        )
        demo_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(demo_vitals_records)").fetchall()
        }
        if "failure_reason" in demo_columns:
            conn.execute(
                """
                UPDATE demo_vitals_records
                SET demo_fallback_reason=failure_reason
                WHERE demo_fallback_reason='' AND failure_reason!=''
                """
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vitals_session_contexts (
              session_id TEXT PRIMARY KEY,
              source_route TEXT NOT NULL,
              inquiry_session_id TEXT NOT NULL DEFAULT '',
              attribution_source TEXT NOT NULL,
              service_user_id TEXT NOT NULL DEFAULT '',
              service_user_name_snapshot TEXT NOT NULL DEFAULT '',
              persona_generation TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              sync_status TEXT NOT NULL,
              pending_count INTEGER NOT NULL,
              last_sync_at TEXT NOT NULL,
              network_mode TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cloud_command_history (
              command_id TEXT PRIMARY KEY,
              command_type TEXT NOT NULL,
              status TEXT NOT NULL,
              result_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              age INTEGER NOT NULL,
              profile TEXT NOT NULL,
              allergies TEXT NOT NULL DEFAULT '',
              note TEXT NOT NULL,
              status TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "service_users", "allergies", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "service_users", "medical_conditions_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "service_users", "current_medications_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "service_users", "allergy_facts_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "service_users", "safety_profile_revision", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "service_users", "safety_profile_updated_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "service_users", "persona_generation", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "service_users", "archived", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS face_identities (
              subject TEXT PRIMARY KEY,
              service_user_id TEXT NOT NULL UNIQUE,
              confidence REAL,
              match_count INTEGER NOT NULL DEFAULT 0,
              enrolled_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              FOREIGN KEY(service_user_id) REFERENCES service_users(id)
            )
            """
        )
        _ensure_column(conn, "face_identities", "match_count", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fingerprint_identities (
              template_id INTEGER PRIMARY KEY,
              service_user_id TEXT NOT NULL UNIQUE,
              score REAL,
              match_count INTEGER NOT NULL DEFAULT 0,
              enrolled_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              FOREIGN KEY(service_user_id) REFERENCES service_users(id)
            )
            """
        )
        _ensure_column(conn, "fingerprint_identities", "match_count", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fingerprint_enrollment_jobs (
              job_id TEXT PRIMARY KEY,
              service_user_id TEXT NOT NULL,
              template_id INTEGER NOT NULL,
              status TEXT NOT NULL,
              event TEXT NOT NULL,
              message TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identity_assertions (
              assertion_id TEXT PRIMARY KEY,
              service_user_id TEXT NOT NULL,
              verification_method TEXT NOT NULL,
              verification_score REAL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              FOREIGN KEY(service_user_id) REFERENCES service_users(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS identity_assertions_user_expiry_idx "
            "ON identity_assertions(service_user_id, expires_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medicine_safety_checks (
              check_id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL UNIQUE,
              request_payload_digest TEXT NOT NULL,
              route TEXT NOT NULL,
              service_user_id TEXT NOT NULL,
              service_user_name_snapshot TEXT NOT NULL,
              persona_generation TEXT NOT NULL,
              safety_profile_revision INTEGER NOT NULL,
              person_safety_fingerprint TEXT NOT NULL,
              verification_method TEXT NOT NULL,
              verification_assertion_id TEXT NOT NULL,
              medicine_id TEXT NOT NULL,
              medicine_name_snapshot TEXT NOT NULL,
              slot TEXT NOT NULL,
              hardware_slot_snapshot INTEGER NOT NULL,
              stock_snapshot INTEGER NOT NULL,
              review_fingerprint TEXT NOT NULL,
              check_status TEXT NOT NULL,
              reason_codes_json TEXT NOT NULL,
              reason_summary TEXT NOT NULL,
              ruleset_version TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              consumed_at TEXT NOT NULL DEFAULT '',
              dispense_status TEXT NOT NULL DEFAULT 'NOT_STARTED',
              dispense_record_id TEXT NOT NULL DEFAULT '',
              qsm_operation_id TEXT NOT NULL DEFAULT '',
              confirm_request_id TEXT NOT NULL DEFAULT '',
              confirm_payload_digest TEXT NOT NULL DEFAULT '',
              confirm_message TEXT NOT NULL DEFAULT '',
              confirm_completed_at TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "medicine_safety_checks", "confirm_request_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicine_safety_checks", "confirm_payload_digest", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicine_safety_checks", "confirm_message", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicine_safety_checks", "confirm_completed_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "medicine_safety_checks", "hardware_slot_snapshot", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "medicine_safety_checks", "stock_snapshot", "INTEGER NOT NULL DEFAULT -1")
        _ensure_column(conn, "medicine_safety_checks", "person_safety_fingerprint", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS medicine_safety_checks_confirm_request_idx "
            "ON medicine_safety_checks(confirm_request_id) WHERE confirm_request_id<>''"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS medicine_safety_checks_user_created_idx "
            "ON medicine_safety_checks(service_user_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS medicine_safety_checks_status_created_idx "
            "ON medicine_safety_checks(check_status, created_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medication_safety_outbox (
              event_id TEXT PRIMARY KEY,
              aggregate_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              payload_digest TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              sent_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS medication_safety_outbox_pending_idx "
            "ON medication_safety_outbox(status, next_attempt_at, created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS today_plans (
              id TEXT PRIMARY KEY,
              time TEXT NOT NULL,
              medicine_id TEXT NOT NULL DEFAULT '',
              service_user_id TEXT NOT NULL DEFAULT '',
              persona_generation TEXT NOT NULL DEFAULT '',
              dose TEXT NOT NULL DEFAULT '按说明',
              status TEXT NOT NULL,
              medicine TEXT NOT NULL DEFAULT '',
              target_user TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        _ensure_column(conn, "today_plans", "medicine_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "service_user_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "persona_generation", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "dose", "TEXT NOT NULL DEFAULT '按说明'")
        _ensure_column(conn, "today_plans", "timing_label", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "updated_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "schedule_type", "TEXT NOT NULL DEFAULT 'daily'")
        _ensure_column(conn, "today_plans", "interval_days", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "today_plans", "weekdays_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "today_plans", "start_date", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "last_action_date", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "dispense_operation_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "dispense_operation_date", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "dispense_operation_state", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "today_plans", "archived", "INTEGER NOT NULL DEFAULT 0")
        _migrate_today_plans(conn)
        _seed_service_data(conn)
        _backfill_persona_generations(conn)
        _backfill_today_plan_persona_generations(conn)
        conn.execute(
            """
            UPDATE today_plans SET archived=1
            WHERE archived=0
              AND service_user_id IN (SELECT id FROM service_users WHERE archived=1)
            """,
        )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in columns:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            raise


def _migrate_today_plans(conn: sqlite3.Connection) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        """
        UPDATE today_plans
        SET service_user_id=COALESCE(
          (
            SELECT MIN(service_users.id)
            FROM service_users
            WHERE service_users.name=today_plans.target_user
              AND service_users.archived=0
            GROUP BY service_users.name
            HAVING COUNT(*)=1
          ),
          ''
        )
        WHERE service_user_id='' AND archived=0
        """
    )
    conn.execute(
        """
        UPDATE today_plans
        SET medicine_id=COALESCE(
          (
            SELECT MIN(medicines.id)
            FROM medicines
            WHERE medicines.name=today_plans.medicine
            GROUP BY medicines.name
            HAVING COUNT(*)=1
          ),
          ''
        )
        WHERE medicine_id='' AND archived=0
        """
    )
    # Legacy free-text plans are user data. If an old person or medicine label
    # cannot be resolved unambiguously, quarantine the row instead of deleting
    # it or guessing a new owner/medicine.
    conn.execute(
        """
        UPDATE today_plans SET archived=1
        WHERE archived=0 AND (
          service_user_id=''
          OR medicine_id=''
          OR NOT EXISTS (
            SELECT 1 FROM service_users
            WHERE service_users.id=today_plans.service_user_id
              AND service_users.archived=0
          )
          OR NOT EXISTS (
            SELECT 1 FROM medicines
            WHERE medicines.id=today_plans.medicine_id
          )
        )
        """
    )
    conn.execute(
        """
        UPDATE today_plans
        SET target_user=(SELECT name FROM service_users WHERE id=today_plans.service_user_id),
            medicine=(SELECT name FROM medicines WHERE id=today_plans.medicine_id),
            updated_at=CASE WHEN updated_at='' THEN ? ELSE updated_at END
        WHERE archived=0
        """,
        (now_text(),),
    )
    conn.execute("UPDATE today_plans SET start_date=? WHERE start_date=''", (today,))
    conn.execute("UPDATE today_plans SET interval_days=1 WHERE interval_days<1")
    conn.execute("UPDATE today_plans SET schedule_type='daily' WHERE schedule_type NOT IN ('daily', 'interval', 'weekly')")


def _backfill_persona_generations(conn: sqlite3.Connection) -> None:
    """Give every valid legacy person one persisted ownership generation."""
    rows = conn.execute(
        """
        SELECT id FROM service_users
        WHERE TRIM(id)<>''
          AND TRIM(name)<>''
          AND TRIM(persona_generation)=''
        """
    ).fetchall()
    for row in rows:
        generation = f"persona-{uuid4().hex}"
        conn.execute(
            """
            UPDATE service_users
            SET persona_generation=?
            WHERE id=? AND TRIM(persona_generation)=''
            """,
            (generation, str(row["id"])),
        )
        _bind_blank_persona_generations(
            conn,
            user_id=str(row["id"]),
            persona_generation=generation,
        )


def _bind_blank_persona_generations(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    persona_generation: str,
) -> None:
    """Bind only pre-generation inquiry rows to a person's first generation."""
    conn.execute(
        """
        UPDATE inquiry_sessions
        SET persona_generation=?
        WHERE user_id=? AND TRIM(persona_generation)=''
        """,
        (persona_generation, user_id),
    )
    conn.execute(
        """
        UPDATE dispense_records
        SET persona_generation=?
        WHERE target_user_id=? AND TRIM(persona_generation)=''
        """,
        (persona_generation, user_id),
    )


def _backfill_today_plan_persona_generations(conn: sqlite3.Connection) -> None:
    """Bind legacy plans once; never derive their owner generation at read time."""
    conn.execute(
        """
        UPDATE today_plans
        SET persona_generation=(
          SELECT persona_generation
          FROM service_users
          WHERE service_users.id=today_plans.service_user_id
        )
        WHERE TRIM(persona_generation)=''
          AND EXISTS (
            SELECT 1 FROM service_users
            WHERE service_users.id=today_plans.service_user_id
              AND TRIM(service_users.persona_generation)<>''
          )
        """
    )


def health_check() -> dict[str, object]:
    init_db()
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"ok": True, "db_path": str(settings.db_path)}


def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now_text()),
        )


def _seed_service_data(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) AS count FROM sync_state").fetchone()["count"] == 0:
        conn.execute(
            """
            INSERT INTO sync_state(id, sync_status, pending_count, last_sync_at, network_mode)
            VALUES (1, '待同步', 0, '未同步', '本地记录')
            """
        )
    seed_version = "family-safety-personas-v2-legacy-v6-archive"
    seed = conn.execute(
        "SELECT value FROM app_settings WHERE key='service_user_seed_version'"
    ).fetchone()
    fingerprint_seed = conn.execute(
        "SELECT value FROM app_settings WHERE key='service_user_seed_fingerprints'"
    ).fetchone()
    _archive_exact_legacy_v6_personas(conn)
    if seed and str(seed["value"]) == seed_version and fingerprint_seed:
        return

    now = now_text()
    users = (
        (
            "wang-nainai",
            "王奶奶",
            72,
            "高血压；常年性过敏性鼻炎；既往胃溃疡；独居",
            "青霉素类药物过敏",
            "女儿为已绑定家属；计划用药按既往有效医嘱执行",
            "重点照护",
            [
                {"concept_code": "hypertension", "display_text": "高血压", "status": "present", "source": "demo_profile_review", "reviewed_at": "2026-08-10"},
                {"concept_code": "allergic_rhinitis", "display_text": "常年性过敏性鼻炎", "status": "present", "source": "demo_profile_review", "reviewed_at": "2026-08-10"},
                {"concept_code": "peptic_ulcer", "display_text": "既往胃溃疡", "status": "present", "source": "demo_profile_review", "reviewed_at": "2026-08-10"},
            ],
            [
                {"medicine_id": "slot-21-amlodipine", "medicine_name": "苯磺酸氨氯地平片", "active_ingredients": ["氨氯地平"], "schedule": "08:00 早餐后", "source": "demo_plan_review", "updated_at": "2026-08-10"},
                {"medicine_id": "slot-18-budesonide-nasal", "medicine_name": "布地奈德鼻喷雾剂", "active_ingredients": ["布地奈德"], "schedule": "21:00 睡前", "source": "demo_plan_review", "updated_at": "2026-08-10"},
            ],
            [
                {"concept_code": "penicillin_allergy", "display_text": "青霉素类药物过敏", "status": "present", "source": "demo_profile_review", "reviewed_at": "2026-08-10"},
            ],
        ),
        (
            "li-yeye",
            "李爷爷",
            74,
            "2 型糖尿病；功能性便秘；季节性过敏性鼻炎；独居",
            "无已知药物过敏",
            "儿子为已绑定家属；计划用药按既往有效医嘱执行",
            "重点照护",
            [
                {"concept_code": "diabetes", "display_text": "2 型糖尿病", "status": "present", "source": "demo_profile_review", "reviewed_at": "2026-08-10"},
                {"concept_code": "functional_constipation", "display_text": "功能性便秘", "status": "present", "source": "demo_profile_review", "reviewed_at": "2026-08-10"},
                {"concept_code": "allergic_rhinitis", "display_text": "季节性过敏性鼻炎", "status": "present", "source": "demo_profile_review", "reviewed_at": "2026-08-10"},
            ],
            [
                {"medicine_id": "slot-06-lactulose", "medicine_name": "乳果糖口服液", "active_ingredients": ["乳果糖"], "schedule": "07:30 早餐时", "source": "demo_plan_review", "updated_at": "2026-08-10"},
                {"medicine_id": "slot-23-desloratadine", "medicine_name": "枸地氯雷他定胶囊", "active_ingredients": ["枸地氯雷他定"], "schedule": "20:30 睡前", "source": "demo_plan_review", "updated_at": "2026-08-10"},
            ],
            [],
        ),
    )
    for user in users:
        conn.execute(
            """
            INSERT INTO service_users(
              id, name, age, profile, allergies, note, status,
              medical_conditions_json, current_medications_json, allergy_facts_json,
              safety_profile_revision, safety_profile_updated_at, persona_generation, archived
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'senior-demo-v1', 0)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                user[0], user[1], user[2], user[3], user[4], user[5], user[6],
                json.dumps(user[7], ensure_ascii=False),
                json.dumps(user[8], ensure_ascii=False),
                json.dumps(user[9], ensure_ascii=False),
                now,
            ),
        )

    expected_fingerprints = {
        user[0]: _service_user_identity_fingerprint(
            {
                "id": user[0],
                "name": user[1],
                "age": user[2],
                "profile": user[3],
                "allergies": user[4],
                "note": user[5],
                "status": user[6],
                "medical_conditions_json": user[7],
                "current_medications_json": user[8],
                "allergy_facts_json": user[9],
                "safety_profile_revision": 1,
                "persona_generation": "senior-demo-v1",
                "archived": 0,
            }
        )
        for user in users
    }
    conn.execute(
        """
        INSERT INTO app_settings(key, value, updated_at)
        VALUES ('service_user_seed_fingerprints', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (json.dumps(expected_fingerprints, ensure_ascii=False, sort_keys=True), now),
    )

    conn.execute(
        """
        INSERT INTO app_settings(key, value, updated_at)
        VALUES ('service_user_seed_version', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (seed_version, now),
    )


def _archive_exact_legacy_v6_personas(conn: sqlite3.Connection) -> None:
    """Archive untouched v6 demo people while retaining their stable ownership IDs."""
    expected_by_name = {
        "张三": {
            "age": 70,
            "profile": "高血压；常年性过敏性鼻炎；李四的爷爷和主要照护人",
            "allergies": "头孢类药物禁忌",
            "note": "父母外出工作时负责照护李四；本人降压药和鼻喷剂按既往医嘱使用",
            "status": "家庭监护人",
        },
        "李四": {
            "age": 8,
            "profile": "8岁儿童；体重约25公斤；季节性过敏性鼻炎；功能性便秘",
            "allergies": "无已知药物过敏",
            "note": "张三的孙子；父母工作日外出，由张三照护；儿童用药需由监护人核验",
            "status": "儿童家庭成员",
        },
        "王五": {
            "age": 58,
            "profile": "长期胃病",
            "allergies": "",
            "note": "近期有问询",
            "status": "观察",
        },
    }
    rows = conn.execute(
        """
        SELECT id, name, age, profile, allergies, note, status,
               medical_conditions_json, current_medications_json,
               allergy_facts_json, safety_profile_revision,
               safety_profile_updated_at, persona_generation, archived
        FROM service_users
        WHERE name IN ('张三', '李四', '王五') AND archived=0
        """
    ).fetchall()
    for row in rows:
        expected = expected_by_name[str(row["name"])]
        unchanged = all(
            (
                int(row["age"] or 0) == expected["age"],
                str(row["profile"] or "") == expected["profile"],
                str(row["allergies"] or "") == expected["allergies"],
                str(row["note"] or "") == expected["note"],
                str(row["status"] or "") == expected["status"],
                str(row["medical_conditions_json"] or "[]") == "[]",
                str(row["current_medications_json"] or "[]") == "[]",
                str(row["allergy_facts_json"] or "[]") == "[]",
                int(row["safety_profile_revision"] or 1) == 1,
                str(row["safety_profile_updated_at"] or "") == "",
                str(row["persona_generation"] or "") == "",
            )
        )
        if not unchanged:
            continue
        conn.execute(
            """
            UPDATE service_users
            SET archived=1, persona_generation='legacy-family-demo-v6'
            WHERE id=? AND archived=0 AND TRIM(persona_generation)=''
            """,
            (row["id"],),
        )
        _bind_blank_persona_generations(
            conn,
            user_id=str(row["id"]),
            persona_generation="legacy-family-demo-v6",
        )


def has_exact_senior_demo_personas(conn: sqlite3.Connection) -> bool:
    """Return true only when both reserved demo IDs still hold exact seeded identities."""
    stored = conn.execute(
        "SELECT value FROM app_settings WHERE key='service_user_seed_fingerprints'"
    ).fetchone()
    if stored is None:
        return False
    try:
        expected = json.loads(str(stored["value"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(expected, dict) or set(expected) != {"wang-nainai", "li-yeye"}:
        return False
    rows = conn.execute(
        """
        SELECT id, name, age, profile, allergies, note, status,
               medical_conditions_json, current_medications_json,
               allergy_facts_json, safety_profile_revision,
               persona_generation, archived
        FROM service_users
        WHERE id IN ('wang-nainai', 'li-yeye')
        """
    ).fetchall()
    actual = {
        str(row["id"]): _service_user_identity_fingerprint(dict(row))
        for row in rows
    }
    return actual == {str(key): str(value) for key, value in expected.items()}


def _service_user_identity_fingerprint(values: dict[str, object]) -> str:
    def json_list(value: object) -> list[object]:
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []

    payload = {
        "id": str(values.get("id") or ""),
        "name": str(values.get("name") or ""),
        "age": int(values.get("age") or 0),
        "profile": str(values.get("profile") or ""),
        "allergies": str(values.get("allergies") or ""),
        "note": str(values.get("note") or ""),
        "status": str(values.get("status") or ""),
        "medical_conditions": json_list(values.get("medical_conditions_json")),
        "current_medications": json_list(values.get("current_medications_json")),
        "allergy_facts": json_list(values.get("allergy_facts_json")),
        "safety_profile_revision": int(values.get("safety_profile_revision") or 0),
        "persona_generation": str(values.get("persona_generation") or ""),
        "archived": bool(values.get("archived")),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
