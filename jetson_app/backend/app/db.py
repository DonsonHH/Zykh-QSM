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
            CREATE TABLE IF NOT EXISTS site_profile (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              station_name TEXT DEFAULT '偏远社区康护站',
              station_type TEXT DEFAULT 'village',
              location_name TEXT DEFAULT '村镇智慧用药服务点',
              altitude INTEGER DEFAULT 0,
              environment_tags TEXT DEFAULT '弱网,村镇,慢病随访,应急药品供给',
              network_mode TEXT DEFAULT 'weak',
              ai_mode TEXT DEFAULT 'local',
              emergency_contact TEXT DEFAULT '村医 / 管理员',
              manager_name TEXT DEFAULT '值守管理员',
              last_sync_at TEXT DEFAULT '',
              pending_sync_count INTEGER DEFAULT 0,
              sync_status TEXT DEFAULT '待同步',
              updated_at TEXT NOT NULL
            );

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

            CREATE TABLE IF NOT EXISTS emergency_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              scene_type TEXT DEFAULT '',
              network_mode TEXT DEFAULT '',
              symptoms_text TEXT DEFAULT '',
              vitals_snapshot TEXT DEFAULT '',
              allergy_or_contraindication TEXT DEFAULT '',
              current_medicine_context TEXT DEFAULT '',
              ai_mode TEXT DEFAULT 'rules',
              risk_level TEXT DEFAULT 'low',
              symptoms_summary TEXT DEFAULT '',
              suggested_categories TEXT DEFAULT '',
              candidate_medicines TEXT DEFAULT '',
              safety_warnings TEXT DEFAULT '',
              next_steps TEXT DEFAULT '',
              need_admin_review INTEGER DEFAULT 1,
              allow_self_confirm INTEGER DEFAULT 0,
              action_summary TEXT DEFAULT '',
              sync_status TEXT DEFAULT 'pending',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dispense_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id INTEGER DEFAULT NULL,
              plan_id INTEGER DEFAULT NULL,
              slot INTEGER NOT NULL,
              medicine_name TEXT DEFAULT '',
              quantity INTEGER DEFAULT 1,
              reason TEXT DEFAULT '',
              confirmed_by_user INTEGER DEFAULT 0,
              admin_reviewed INTEGER DEFAULT 0,
              dry_run INTEGER DEFAULT 1,
              success INTEGER DEFAULT 0,
              detail TEXT DEFAULT '',
              sync_status TEXT DEFAULT 'pending',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS network_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              mode TEXT DEFAULT '',
              ai_mode TEXT DEFAULT '',
              reason TEXT DEFAULT '',
              sync_status TEXT DEFAULT 'pending',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS offline_knowledge (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT DEFAULT '',
              category TEXT DEFAULT '',
              symptoms_tags TEXT DEFAULT '',
              medicine_category TEXT DEFAULT '',
              warning TEXT DEFAULT '',
              content TEXT DEFAULT '',
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS operator_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              operator TEXT DEFAULT 'system',
              action TEXT NOT NULL,
              target_type TEXT DEFAULT '',
              target_id TEXT DEFAULT '',
              detail TEXT DEFAULT '',
              sync_status TEXT DEFAULT 'pending',
              created_at TEXT NOT NULL
            );
            """
        )
        ensure_medicine_columns(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO site_profile
            (id, station_name, station_type, location_name, altitude, environment_tags,
             network_mode, ai_mode, emergency_contact, manager_name, last_sync_at,
             pending_sync_count, sync_status, updated_at)
            VALUES (1, '偏远社区康护站', 'village', '村镇智慧用药服务点', 0,
                    '弱网,村镇,慢病随访,应急药品供给', 'weak', 'local',
                    '村医 / 管理员', '值守管理员', '', 0, '待同步', ?)
            """,
            (now_text(),),
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
                (slot, name, dosage, stock, expire_date, code, trace_code, box_size,
                 category, indication_tags, contraindications, dosage_note, safety_note,
                 unit, barcode, image_path, is_emergency, is_daily_plan_medicine, updated_at)
                VALUES (?, '', '', 0, '', '', '', ?, '其他应急', '', '', '', '',
                        '件', '', '', 1, 0, ?)
                """,
                (slot, slot_kind(slot), now_text()),
            )
        seed_offline_knowledge(conn)


def ensure_medicine_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(medicines)").fetchall()}
    columns = {
        "category": "TEXT DEFAULT '其他应急'",
        "indication_tags": "TEXT DEFAULT ''",
        "contraindications": "TEXT DEFAULT ''",
        "dosage_note": "TEXT DEFAULT ''",
        "safety_note": "TEXT DEFAULT ''",
        "unit": "TEXT DEFAULT '件'",
        "barcode": "TEXT DEFAULT ''",
        "image_path": "TEXT DEFAULT ''",
        "is_emergency": "INTEGER DEFAULT 1",
        "is_daily_plan_medicine": "INTEGER DEFAULT 0",
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE medicines ADD COLUMN {name} {ddl}")
    conn.execute("UPDATE medicines SET barcode=code WHERE (barcode IS NULL OR barcode='') AND code<>''")


def seed_offline_knowledge(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM offline_knowledge").fetchone()[0]
    if count:
        return
    now = now_text()
    items = [
        ("发热感冒初筛", "感冒发热", "发热,咽痛,流涕", "感冒发热", "高热不退、呼吸困难、意识异常需联系医生或救援。", "优先补水休息，核对过敏史、既往用药和药品说明书。仅匹配已录入的非处方应急药品。"),
        ("肠胃不适初筛", "肠胃", "腹泻,腹痛,呕吐", "肠胃", "持续腹痛、便血、脱水或老人儿童症状明显需人工复核。", "关注补液和饮食，避免重复用药，必要时联系村医。"),
        ("过敏风险提示", "过敏", "皮疹,瘙痒,过敏", "过敏", "呼吸困难、喉头水肿、全身严重过敏属于紧急风险。", "先确认过敏源和既往过敏史，普通终端不替代医生判断。"),
        ("慢病用药提醒", "慢病常用", "高血压,糖尿病,慢病", "慢病常用", "不要自行新增、停用或调整处方药剂量。", "按既有计划提醒服药，异常体征或不适应联系医生/管理员。"),
    ]
    for title, category, symptoms_tags, medicine_category, warning, content in items:
        conn.execute(
            """
            INSERT INTO offline_knowledge(title,category,symptoms_tags,medicine_category,warning,content,updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (title, category, symptoms_tags, medicine_category, warning, content, now),
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


def add_operator_log(action: str, detail: str = "", target_type: str = "", target_id: str = "", operator: str = "system") -> None:
    execute(
        "INSERT INTO operator_logs(operator, action, target_type, target_id, detail, created_at) VALUES (?,?,?,?,?,?)",
        (operator, action, target_type, target_id, detail, now_text()),
    )
