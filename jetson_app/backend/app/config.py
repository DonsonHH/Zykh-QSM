from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parent
DATA_DIR = Path(os.getenv("JETSON_DATA_DIR", APP_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("JETSON_DB_PATH", DATA_DIR / "zykh_jetson.db"))
AI_KEY_FILE = Path(os.getenv("AI_API_KEY_FILE", DATA_DIR / "ai-api-key.txt"))

QSM_API_BASE = os.getenv("QSM_API_BASE", "http://127.0.0.1:18080").rstrip("/")
QSM_ADB_LOCAL_PORT = int(os.getenv("QSM_ADB_LOCAL_PORT", "18080"))
QSM_ADB_REMOTE_PORT = int(os.getenv("QSM_ADB_REMOTE_PORT", "8080"))
QSM_ADB_AUTO_FORWARD = os.getenv("QSM_ADB_AUTO_FORWARD", "1") != "0"

AI_API_BASE = os.getenv("AI_API_BASE", "https://api.deepseek.com/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-v4-flash")

KIOSK_HOST = os.getenv("JETSON_HOST", "127.0.0.1")
KIOSK_PORT = int(os.getenv("JETSON_PORT", "8088"))

