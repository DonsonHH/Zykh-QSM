from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("ZYKH_STATION_DATA_DIR", APP_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    app_name: str = "Zykh Station App"
    host: str = os.getenv("ZYKH_STATION_HOST", "127.0.0.1")
    port: int = int(os.getenv("ZYKH_STATION_PORT", "8000"))
    db_path: Path = Path(os.getenv("ZYKH_STATION_DB", DATA_DIR / "station.db"))
    qsm_mode: str = os.getenv("QSM_MODE", "real").strip().lower()
    qsm_api_base: str = os.getenv("QSM_BASE_URL", os.getenv("QSM_API_BASE", "http://127.0.0.1:18080")).rstrip("/")
    qsm_timeout_seconds: float = float(os.getenv("QSM_TIMEOUT_SECONDS", "2"))
    qsm_status_path: str = os.getenv("QSM_STATUS_PATH", "/api/status")
    qsm_vitals_path: str = os.getenv("QSM_VITALS_PATH", "/api/vitals/read")
    qsm_vitals_all_path: str = os.getenv("QSM_VITALS_ALL_PATH", "/api/vitals/read_all")
    qsm_temp_path: str = os.getenv("QSM_TEMP_PATH", "/api/vitals/temp/read")
    qsm_camera_capture_path: str = os.getenv("QSM_CAMERA_CAPTURE_PATH", "/api/camera/capture")
    qsm_dispense_path: str = os.getenv("QSM_DISPENSE_PATH", "/api/dispense")
    qsm_audio_asr_path: str = os.getenv("QSM_AUDIO_ASR_PATH", "/api/audio/asr")
    qsm_audio_speak_path: str = os.getenv("QSM_AUDIO_SPEAK_PATH", "/api/audio/speak")
    qsm_audio_beep_path: str = os.getenv("QSM_AUDIO_BEEP_PATH", "/api/audio/beep")
    local_camera_mode: str = os.getenv("LOCAL_CAMERA_MODE", "real").strip().lower()
    local_camera_device: str = os.getenv("LOCAL_CAMERA_DEVICE", "auto")
    local_camera_capture_cmd: str = os.getenv("LOCAL_CAMERA_CAPTURE_CMD", "")
    medicine_scan_cmd: str = os.getenv("MEDICINE_SCAN_CMD", "")
    ai_mode: str = os.getenv("AI_MODE", "auto").strip().lower()
    ai_api_base: str = os.getenv("AI_API_BASE", "https://api.deepseek.com/chat/completions")
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_api_key_file: Path = Path(os.getenv("AI_API_KEY_FILE", "/userdata/zykh_app/data/ai-api-key.txt"))
    ai_model: str = os.getenv("AI_MODEL", "deepseek-v4-flash")
    dashscope_api_base: str = os.getenv(
        "DASHSCOPE_API_BASE",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_api_key_file: Path = Path(os.getenv("DASHSCOPE_API_KEY_FILE", "/userdata/zykh_app/data/dashscope-api-key.txt"))
    qwen_vision_model: str = os.getenv("QWEN_VISION_MODEL", "qwen3.6-flash")
    showapi_app_key_file: Path = Path(os.getenv("SHOWAPI_APP_KEY_FILE", "/userdata/zykh_app/data/showapi-app-key.txt"))
    sync_endpoint: str = os.getenv("SYNC_ENDPOINT", "")
    real_dispense_test_slot: str = os.getenv("REAL_DISPENSE_TEST_SLOT", "")
    dispense_dry_run: bool = os.getenv("DISPENSE_DRY_RUN", "false").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


settings = Settings()
