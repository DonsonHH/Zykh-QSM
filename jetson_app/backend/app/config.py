from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parent
DATA_DIR = Path(os.getenv("QSM_DATA_DIR") or os.getenv("JETSON_DATA_DIR") or APP_ROOT / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

_legacy_db_path = DATA_DIR / "zykh_jetson.db"
_default_db_path = _legacy_db_path if _legacy_db_path.exists() else DATA_DIR / "zykh_qsm.db"
DB_PATH = Path(os.getenv("QSM_DB_PATH") or os.getenv("JETSON_DB_PATH") or _default_db_path)
AI_KEY_FILE = Path(os.getenv("AI_API_KEY_FILE", DATA_DIR / "ai-api-key.txt"))

QSM_API_BASE = os.getenv("QSM_API_BASE", "http://127.0.0.1:18080").rstrip("/")
QSM_ADB_LOCAL_PORT = int(os.getenv("QSM_ADB_LOCAL_PORT", "18080"))
QSM_ADB_REMOTE_PORT = int(os.getenv("QSM_ADB_REMOTE_PORT", "8080"))
QSM_ADB_AUTO_FORWARD = os.getenv("QSM_ADB_AUTO_FORWARD", "1") != "0"

AI_API_BASE = os.getenv("AI_API_BASE", "https://api.deepseek.com/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-v4-flash")

KIOSK_HOST = os.getenv("QSM_HOST") or os.getenv("JETSON_HOST", "127.0.0.1")
KIOSK_PORT = int(os.getenv("QSM_PORT") or os.getenv("JETSON_PORT", "8088"))
