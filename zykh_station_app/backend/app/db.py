from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

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
              tags_json TEXT NOT NULL,
              contraindications_json TEXT NOT NULL,
              stock INTEGER NOT NULL,
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
            CREATE TABLE IF NOT EXISTS today_plans (
              id TEXT PRIMARY KEY,
              time TEXT NOT NULL,
              medicine_id TEXT NOT NULL DEFAULT '',
              service_user_id TEXT NOT NULL DEFAULT '',
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
        _ensure_column(conn, "today_plans", "dose", "TEXT NOT NULL DEFAULT '按说明'")
        _ensure_column(conn, "today_plans", "updated_at", "TEXT NOT NULL DEFAULT ''")
        _migrate_today_plans(conn)
        _seed_service_data(conn)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_today_plans(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE today_plans
        SET service_user_id=COALESCE(
          (SELECT service_users.id FROM service_users WHERE service_users.name=today_plans.target_user LIMIT 1),
          ''
        )
        WHERE service_user_id=''
        """
    )
    conn.execute(
        """
        UPDATE today_plans
        SET medicine_id=COALESCE(
          (SELECT medicines.id FROM medicines WHERE medicines.name=today_plans.medicine LIMIT 1),
          ''
        )
        WHERE medicine_id=''
        """
    )
    conn.execute("DELETE FROM today_plans WHERE service_user_id='' OR medicine_id=''")
    conn.execute(
        """
        UPDATE today_plans
        SET target_user=(SELECT name FROM service_users WHERE id=today_plans.service_user_id),
            medicine=(SELECT name FROM medicines WHERE id=today_plans.medicine_id),
            updated_at=CASE WHEN updated_at='' THEN ? ELSE updated_at END
        """,
        (now_text(),),
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
    if conn.execute("SELECT COUNT(*) AS count FROM service_users").fetchone()["count"] == 0:
        conn.executemany(
            """
            INSERT INTO service_users(id, name, age, profile, allergies, note, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("zhangsan", "张三", 65, "高血压", "头孢过敏；避免头孢类抗生素", "今日演示对象", "重点关注"),
                ("lisi", "李四", 72, "糖尿病", "", "随访对象", "随访"),
                ("wangwu", "王五", 58, "长期胃病", "", "近期有问询", "观察"),
            ],
        )
    else:
        conn.execute(
            """
            UPDATE service_users
            SET allergies='头孢过敏；避免头孢类抗生素',
                note=CASE WHEN note='' OR note='今日有计划' THEN '今日演示对象' ELSE note END
            WHERE name='张三'
            """
        )
