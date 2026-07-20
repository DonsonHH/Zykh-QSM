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
    qsm_timeout_seconds: float = float(_env("QSM_TIMEOUT_SECONDS", "5"))
    qsm_vitals_timeout_seconds: float = float(_env("QSM_VITALS_TIMEOUT_SECONDS", "22"))
    qsm_vitals_retry_attempts: int = max(1, int(_env("QSM_VITALS_RETRY_ATTEMPTS", "1")))
    qsm_vitals_retry_delay_seconds: float = max(0.0, float(_env("QSM_VITALS_RETRY_DELAY_SECONDS", "0.7")))
    qsm_vitals_api_base: str = _env("QSM_VITALS_BASE_URL", "http://127.0.0.1:18085").rstrip("/")
    qsm_vitals_session_start_path: str = _env(
        "QSM_VITALS_SESSION_START_PATH", "/api/vitals/session/start"
    )
    qsm_vitals_session_status_path: str = _env(
        "QSM_VITALS_SESSION_STATUS_PATH", "/api/vitals/session/status"
    )
    qsm_vitals_session_cancel_path: str = _env(
        "QSM_VITALS_SESSION_CANCEL_PATH", "/api/vitals/session/cancel"
    )
    qsm_audio_timeout_seconds: float = float(_env("QSM_AUDIO_TIMEOUT_SECONDS", "120"))
    qsm_mic_api_base: str = _env("QSM_MIC_BASE_URL", "http://127.0.0.1:18082").rstrip("/")
    qsm_mic_timeout_seconds: float = float(_env("QSM_MIC_TIMEOUT_SECONDS", "5"))
    qsm_mic_stream_max_seconds: int = max(60, int(_env("QSM_MIC_STREAM_MAX_SECONDS", "600")))
    qsm_mic_status_path: str = _env("QSM_MIC_STATUS_PATH", "/api/audio/capture/status")
    qsm_mic_stream_path: str = _env("QSM_MIC_STREAM_PATH", "/api/audio/capture/stream")
    qsm_mic_record_path: str = _env("QSM_MIC_RECORD_PATH", "/api/audio/capture/record")
    qsm_mic_volume_path: str = _env("QSM_MIC_VOLUME_PATH", "/api/audio/capture/volume")
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
    qsm_face_api_base: str = _env("QSM_FACE_BASE_URL", "http://127.0.0.1:18081").rstrip("/")
    qsm_face_timeout_seconds: float = float(_env("QSM_FACE_TIMEOUT_SECONDS", "25"))
    qsm_face_status_path: str = _env("QSM_FACE_STATUS_PATH", "/api/face/status")
    qsm_face_identify_path: str = _env("QSM_FACE_IDENTIFY_PATH", "/api/face/identify")
    qsm_face_enroll_path: str = _env("QSM_FACE_ENROLL_PATH", "/api/face/enroll")
    qsm_face_list_path: str = _env("QSM_FACE_LIST_PATH", "/api/face/list")
    qsm_face_preview_path: str = _env("QSM_FACE_PREVIEW_PATH", "/api/face/frame")
    qsm_fingerprint_api_base: str = _env("QSM_FINGERPRINT_BASE_URL", "http://127.0.0.1:18086").rstrip("/")
    qsm_fingerprint_timeout_seconds: float = float(_env("QSM_FINGERPRINT_TIMEOUT_SECONDS", "70"))
    qsm_fingerprint_status_path: str = _env("QSM_FINGERPRINT_STATUS_PATH", "/api/fingerprint/status")
    qsm_fingerprint_identify_path: str = _env("QSM_FINGERPRINT_IDENTIFY_PATH", "/api/fingerprint/identify")
    qsm_fingerprint_enroll_path: str = _env("QSM_FINGERPRINT_ENROLL_PATH", "/api/fingerprint/enroll")
    qsm_fingerprint_enroll_start_path: str = _env(
        "QSM_FINGERPRINT_ENROLL_START_PATH", "/api/fingerprint/enroll/start"
    )
    qsm_fingerprint_enroll_progress_path: str = _env(
        "QSM_FINGERPRINT_ENROLL_PROGRESS_PATH", "/api/fingerprint/enroll/progress"
    )
    qsm_fingerprint_delete_path: str = _env("QSM_FINGERPRINT_DELETE_PATH", "/api/fingerprint/delete")
    qsm_fingerprint_standby_path: str = _env("QSM_FINGERPRINT_STANDBY_PATH", "/api/fingerprint/standby")
    qsm_fingerprint_wake_path: str = _env("QSM_FINGERPRINT_WAKE_PATH", "/api/fingerprint/wake")
    qsm_fingerprint_template_start: int = int(_env("QSM_FINGERPRINT_TEMPLATE_START", "16"))
    qsm_dispense_path: str = _env("QSM_DISPENSE_PATH", "/api/dispense")
    qsm_audio_asr_path: str = _env("QSM_AUDIO_ASR_PATH", "/api/audio/asr")
    qsm_audio_status_path: str = _env("QSM_AUDIO_STATUS_PATH", "/api/audio/status")
    qsm_audio_speak_path: str = _env("QSM_AUDIO_SPEAK_PATH", "/api/audio/speak")
    qsm_audio_beep_path: str = _env("QSM_AUDIO_BEEP_PATH", "/api/audio/beep")
    qsm_audio_play_path: str = _env("QSM_AUDIO_PLAY_PATH", "/api/audio/play")
    qsm_audio_stream_start_path: str = _env("QSM_AUDIO_STREAM_START_PATH", "/api/audio/stream/start")
    qsm_audio_stream_stop_path: str = _env("QSM_AUDIO_STREAM_STOP_PATH", "/api/audio/stream/stop")
    qsm_audio_stream_host: str = _env("QSM_AUDIO_STREAM_HOST", "127.0.0.1")
    qsm_audio_stream_port: int = int(_env("QSM_AUDIO_STREAM_PORT", "19001"))
    qsm_local_asr_url: str = _env("QSM_LOCAL_ASR_URL", "ws://127.0.0.1:18084")
    qsm_local_asr_timeout_seconds: float = float(_env("QSM_LOCAL_ASR_TIMEOUT_SECONDS", "8"))
    qsm_local_asr_model: str = _env(
        "QSM_LOCAL_ASR_MODEL",
        "paraformer-zh-small-2024-03-09-int8-resident",
    )
    qsm_network_status_path: str = _env("QSM_NETWORK_STATUS_PATH", "/api/network/status")
    qsm_network_start_4g_path: str = _env("QSM_NETWORK_START_4G_PATH", "/api/network/start_4g")
    qsm_network_timeout_seconds: float = float(_env("QSM_NETWORK_TIMEOUT_SECONDS", "3"))
    qsm_ai_chat_path: str = _env("QSM_AI_CHAT_PATH", "/api/ai/chat")
    host_mic_device: str = _env("HOST_MIC_DEVICE", "qsm:FF Camera")
    network_preferred_mode: str = _env("NETWORK_PREFERRED_MODE", "sim").strip().lower()
    network_sim_interface: str = _env("NETWORK_SIM_INTERFACE", "usb0")
    network_qsm_tether_script: str = _env(
        "NETWORK_QSM_TETHER_SCRIPT", "/userdata/zykh_app/scripts/start_host_tether.sh"
    )
    network_host_tether_helper: str = _env(
        "NETWORK_HOST_TETHER_HELPER", "/usr/local/sbin/zykh-qsm-tether"
    )
    network_host_tether_address: str = _env("NETWORK_HOST_TETHER_ADDRESS", "192.168.77.2")
    network_host_tether_gateway: str = _env("NETWORK_HOST_TETHER_GATEWAY", "192.168.77.1")
    network_demo_simulate: bool = _env("NETWORK_DEMO_SIMULATE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    admin_debug_pin: str = _env("ADMIN_DEBUG_PIN", "1145")
    admin_session_minutes: int = int(_env("ADMIN_SESSION_MINUTES", "30"))
    admin_allow_system_actions: bool = _env("ADMIN_ALLOW_SYSTEM_ACTIONS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    admin_restart_command: str = _env(
        "ADMIN_RESTART_COMMAND",
        f"sh {APP_ROOT / 'scripts' / 'admin_restart_app.sh'}",
    )
    admin_reboot_command: str = _env("ADMIN_REBOOT_COMMAND", "sudo -n systemctl reboot")
    display_output: str = _env("DISPLAY_OUTPUT", "auto")
    display_name: str = _env("DISPLAY", ":0")
    display_xauthority: str = _env("XAUTHORITY", str(Path.home() / ".Xauthority"))
    local_camera_mode: str = _env("LOCAL_CAMERA_MODE", "real").strip().lower()
    local_camera_device: str = _env("LOCAL_CAMERA_DEVICE", "auto")
    local_camera_capture_cmd: str = _env("LOCAL_CAMERA_CAPTURE_CMD", "")
    medicine_scan_cmd: str = _env("MEDICINE_SCAN_CMD", "")
    ai_mode: str = _env("AI_MODE", "auto").strip().lower()
    ai_api_base: str = _env(
        "AI_API_BASE",
        "https://api.deepseek.com/chat/completions",
    )
    ai_api_key: str = _env("AI_API_KEY", "")
    ai_api_key_file: Path = Path(_env("AI_API_KEY_FILE", str(DATA_DIR / "ai-api-key.txt")))
    ai_model: str = _env("AI_MODEL", "deepseek-v4-flash")
    ai_enable_thinking: bool = _env("AI_ENABLE_THINKING", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    ai_inquiry_enable_thinking: bool = _env("AI_INQUIRY_ENABLE_THINKING", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    ai_chat_timeout_seconds: float = float(_env("AI_CHAT_TIMEOUT_SECONDS", "35"))
    ai_inquiry_timeout_seconds: float = float(_env("AI_INQUIRY_TIMEOUT_SECONDS", "45"))
    ai_inquiry_attempt_timeout_seconds: float = float(
        _env("AI_INQUIRY_ATTEMPT_TIMEOUT_SECONDS", "12")
    )
    ai_inquiry_max_attempts: int = int(_env("AI_INQUIRY_MAX_ATTEMPTS", "2"))
    ai_inquiry_retry_delay_seconds: float = float(
        _env("AI_INQUIRY_RETRY_DELAY_SECONDS", "0.25")
    )
    inquiry_location_name: str = _env("INQUIRY_LOCATION_NAME", "成都")
    inquiry_location_latitude: float = float(_env("INQUIRY_LOCATION_LATITUDE", "30.5728"))
    inquiry_location_longitude: float = float(_env("INQUIRY_LOCATION_LONGITUDE", "104.0668"))
    weather_api_base: str = _env("WEATHER_API_BASE", "https://api.open-meteo.com/v1/forecast")
    weather_timeout_seconds: float = float(_env("WEATHER_TIMEOUT_SECONDS", "2.5"))
    weather_cache_seconds: float = float(_env("WEATHER_CACHE_SECONDS", "600"))
    inquiry_spo2_emergency_below: float = float(_env("INQUIRY_SPO2_EMERGENCY_BELOW", "90"))
    inquiry_spo2_high_max: float = float(_env("INQUIRY_SPO2_HIGH_MAX", "93"))
    inquiry_temperature_high_at: float = float(_env("INQUIRY_TEMPERATURE_HIGH_AT", "39"))
    inquiry_medium_confidence_below: float = float(_env("INQUIRY_MEDIUM_CONFIDENCE_BELOW", "0.65"))
    ai_connectivity_timeout_seconds: float = float(_env("AI_CONNECTIVITY_TIMEOUT_SECONDS", "2"))
    local_ai_base_url: str = _env("LOCAL_AI_BASE_URL", "http://127.0.0.1:18083").rstrip("/")
    local_ai_chat_path: str = _env("LOCAL_AI_CHAT_PATH", "/v1/chat/completions")
    local_ai_health_path: str = _env("LOCAL_AI_HEALTH_PATH", "/health")
    local_ai_model: str = _env("LOCAL_AI_MODEL", "Qwen3.5-0.8B-Q4_K_M")
    local_ai_timeout_seconds: float = float(_env("LOCAL_AI_TIMEOUT_SECONDS", "45"))
    local_ai_health_timeout_seconds: float = float(_env("LOCAL_AI_HEALTH_TIMEOUT_SECONDS", "2"))
    dashscope_api_base: str = _env(
        "DASHSCOPE_API_BASE",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    dashscope_api_key: str = _env("DASHSCOPE_API_KEY", "")
    dashscope_api_key_file: Path = Path(_env("DASHSCOPE_API_KEY_FILE", str(DATA_DIR / "dashscope-api-key.txt")))
    qwen_realtime_tts_url: str = _env("QWEN_REALTIME_TTS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
    qwen_realtime_tts_model: str = _env(
        "QWEN_REALTIME_TTS_MODEL",
        "qwen3-tts-instruct-flash-realtime-2026-01-22",
    )
    qwen_realtime_tts_voice: str = _env("QWEN_REALTIME_TTS_VOICE", "Cherry")
    qwen_realtime_tts_speed: float = float(_env("QWEN_REALTIME_TTS_SPEED", "1.32"))
    qwen_realtime_tts_instructions: str = _env(
        "QWEN_REALTIME_TTS_INSTRUCTIONS",
        "语速适中，停顿自然，吐字清晰，语气温和，适合家庭康护终端播报。",
    )
    qwen_realtime_tts_timeout_seconds: float = float(_env("QWEN_REALTIME_TTS_TIMEOUT_SECONDS", "30"))
    qwen_vision_model: str = _env("QWEN_VISION_MODEL", "qwen3.6-flash")
    showapi_app_key_file: Path = Path(_env("SHOWAPI_APP_KEY_FILE", "/userdata/zykh_app/data/showapi-app-key.txt"))
    sync_endpoint: str = _env("SYNC_ENDPOINT", "")
    cloud_sync_enabled: bool = _env("CLOUD_SYNC_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    cloud_sync_endpoint: str = _env(
        "CLOUD_SYNC_ENDPOINT",
        "https://cloud1-d6gv6t2jf3f2c541c-1441069580.ap-shanghai.app.tcloudbase.com/api",
    )
    cloud_sync_device_id: str = _env("CLOUD_SYNC_DEVICE_ID", "zykh-qsm-001")
    cloud_sync_device_secret: str = _env("CLOUD_SYNC_DEVICE_SECRET", "")
    cloud_sync_device_secret_file: Path = Path(
        _env("CLOUD_SYNC_DEVICE_SECRET_FILE", str(DATA_DIR / "cloud-device-secret.txt"))
    )
    cloud_sync_interval_seconds: float = float(_env("CLOUD_SYNC_INTERVAL_SECONDS", "2"))
    cloud_sync_timeout_seconds: float = float(_env("CLOUD_SYNC_TIMEOUT_SECONDS", "12"))
    cloud_remote_cabinet_enabled: bool = _env("CLOUD_REMOTE_CABINET_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    real_dispense_test_slot: str = _env("REAL_DISPENSE_TEST_SLOT", "")
    enable_real_dispense: bool = _env("ENABLE_REAL_DISPENSE", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    dispense_dry_run: bool = _env("DISPENSE_DRY_RUN", "false").strip().lower() not in {
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
    )
