from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect(path: Path | str = DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]


def row(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.execute(sql, tuple(params))
        got = cur.fetchone()
        return dict(got) if got else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              name TEXT DEFAULT '',
              gender TEXT DEFAULT '',
              age INTEGER DEFAULT 0,
              height TEXT DEFAULT '',
              weight TEXT DEFAULT '',
              conditions TEXT DEFAULT '',
              allergies TEXT DEFAULT '',
              notes TEXT DEFAULT '',
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS medicines (
              slot INTEGER PRIMARY KEY CHECK (slot BETWEEN 1 AND 23),
              name TEXT DEFAULT '',
              dosage TEXT DEFAULT '',
              stock INTEGER DEFAULT 0,
              expire_date TEXT DEFAULT '',
              code TEXT DEFAULT '',
              trace_code TEXT DEFAULT '',
              box_size TEXT DEFAULT '',
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plans (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slot INTEGER NOT NULL,
              time TEXT NOT NULL,
              amount TEXT DEFAULT '1片',
              enabled INTEGER DEFAULT 1,
              created_at TEXT NOT NULL,
              FOREIGN KEY(slot) REFERENCES medicines(slot)
            );

            CREATE TABLE IF NOT EXISTS records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              action TEXT NOT NULL,
              slot INTEGER DEFAULT 0,
              subject TEXT DEFAULT '',
              result TEXT NOT NULL,
              detail TEXT DEFAULT '',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vitals_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              temperature REAL DEFAULT 0,
              heart_rate INTEGER DEFAULT 0,
              spo2 INTEGER DEFAULT 0,
              systolic INTEGER DEFAULT 0,
              diastolic INTEGER DEFAULT 0,
              source TEXT DEFAULT '',
              quality TEXT DEFAULT '',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS health_memories (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT DEFAULT 'note',
              title TEXT DEFAULT '',
              content TEXT DEFAULT '',
              happened_at TEXT DEFAULT '',
              source TEXT DEFAULT 'qsm-main',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS medicine_catalog (
              code TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              dosage TEXT DEFAULT '',
              manufacturer TEXT DEFAULT '',
              batch_no TEXT DEFAULT '',
              expire_date TEXT DEFAULT '',
              trace_code TEXT DEFAULT '',
              note TEXT DEFAULT '',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT DEFAULT '',
              updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO profile
            (id, name, gender, age, height, weight, conditions, allergies, notes, updated_at)
            VALUES (1, '', '', 0, '', '', '', '', '', ?)
            """,
            (now_text(),),
        )
        for slot in range(1, 24):
            conn.execute(
                """
                INSERT OR IGNORE INTO medicines
                (slot, name, dosage, stock, expire_date, code, trace_code, box_size, updated_at)
                VALUES (?, '', '', 0, '', '', '', ?, ?)
                """,
                (slot, slot_kind(slot), now_text()),
            )


def slot_kind(slot: int) -> str:
    if 1 <= slot <= 8:
        return "big"
    if 9 <= slot <= 17:
        return "small"
    return "medium"


def add_record(action: str, result: str, detail: str = "", slot: int = 0, subject: str = "") -> None:
    execute(
        "INSERT INTO records(action, slot, subject, result, detail, created_at) VALUES (?,?,?,?,?,?)",
        (action, slot, subject, result, detail, now_text()),
    )
