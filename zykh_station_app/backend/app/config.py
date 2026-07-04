from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]


def _local_env() -> dict[str, str]:
    path = APP_ROOT / "backend" / ".env.local"
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _env(name: str, default: str = "") -> str:
    return os.getenv(name) or _local_env().get(name, default)


DATA_DIR = Path(_env("ZYKH_STATION_DATA_DIR", str(APP_ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    app_name: str = "Zykh Station App"
    host: str = _env("ZYKH_STATION_HOST", "127.0.0.1")
    port: int = int(_env("ZYKH_STATION_PORT", "8000"))
    db_path: Path = Path(_env("ZYKH_STATION_DB", str(DATA_DIR / "station.db")))
    qsm_mode: str = _env("QSM_MODE", "real").strip().lower()
    qsm_api_base: str = _env("QSM_BASE_URL", _env("QSM_API_BASE", "http://127.0.0.1:18080")).rstrip("/")
    qsm_timeout_seconds: float = float(_env("QSM_TIMEOUT_SECONDS", "2"))
    qsm_vitals_timeout_seconds: float = float(_env("QSM_VITALS_TIMEOUT_SECONDS", "25"))
    qsm_vitals_prefer_full: bool = _env("QSM_VITALS_PREFER_FULL", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    qsm_status_path: str = _env("QSM_STATUS_PATH", "/api/status")
    qsm_vitals_path: str = _env("QSM_VITALS_PATH", "/api/vitals/read")
    qsm_vitals_all_path: str = _env("QSM_VITALS_ALL_PATH", "/api/vitals/read_all")
    qsm_temp_path: str = _env("QSM_TEMP_PATH", "/api/vitals/temp/read")
    qsm_camera_capture_path: str = _env("QSM_CAMERA_CAPTURE_PATH", "/api/camera/capture")
    qsm_camera_stream_path: str = _env("QSM_CAMERA_STREAM_PATH", "/api/camera/stream")
    qsm_dispense_path: str = _env("QSM_DISPENSE_PATH", "/api/dispense")
    qsm_audio_asr_path: str = _env("QSM_AUDIO_ASR_PATH", "/api/audio/asr")
    qsm_audio_speak_path: str = _env("QSM_AUDIO_SPEAK_PATH", "/api/audio/speak")
    qsm_audio_beep_path: str = _env("QSM_AUDIO_BEEP_PATH", "/api/audio/beep")
    qsm_ai_chat_path: str = _env("QSM_AI_CHAT_PATH", "/api/ai/chat")
    local_camera_mode: str = _env("LOCAL_CAMERA_MODE", "real").strip().lower()
    local_camera_device: str = _env("LOCAL_CAMERA_DEVICE", "auto")
    local_camera_capture_cmd: str = _env("LOCAL_CAMERA_CAPTURE_CMD", "")
    medicine_scan_cmd: str = _env("MEDICINE_SCAN_CMD", "")
    ai_mode: str = _env("AI_MODE", "auto").strip().lower()
    ai_api_base: str = _env("AI_API_BASE", "https://api.deepseek.com/chat/completions")
    ai_api_key: str = _env("AI_API_KEY", "")
    ai_api_key_file: Path = Path(_env("AI_API_KEY_FILE", "/userdata/zykh_app/data/ai-api-key.txt"))
    ai_model: str = _env("AI_MODEL", "deepseek-v4-flash")
    dashscope_api_base: str = _env(
        "DASHSCOPE_API_BASE",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    dashscope_api_key: str = _env("DASHSCOPE_API_KEY", "")
    dashscope_api_key_file: Path = Path(_env("DASHSCOPE_API_KEY_FILE", "/userdata/zykh_app/data/dashscope-api-key.txt"))
    qwen_vision_model: str = _env("QWEN_VISION_MODEL", "qwen3.6-flash")
    showapi_app_key_file: Path = Path(_env("SHOWAPI_APP_KEY_FILE", "/userdata/zykh_app/data/showapi-app-key.txt"))
    sync_endpoint: str = _env("SYNC_ENDPOINT", "")
    real_dispense_test_slot: str = _env("REAL_DISPENSE_TEST_SLOT", "")
    enable_real_dispense: bool = _env("ENABLE_REAL_DISPENSE", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    dispense_dry_run: bool = _env("DISPENSE_DRY_RUN", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


settings = Settings()


def real_dispense_enabled() -> bool:
    return (
        settings.dispense_dry_run is False
        and settings.enable_real_dispense is True
        and bool(settings.real_dispense_test_slot.strip())
    )
