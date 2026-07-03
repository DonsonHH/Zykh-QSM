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
    qsm_mode: str = os.getenv("QSM_MODE", "mock").strip().lower()
    qsm_api_base: str = os.getenv("QSM_BASE_URL", os.getenv("QSM_API_BASE", "http://127.0.0.1:18080")).rstrip("/")
    qsm_timeout_seconds: float = float(os.getenv("QSM_TIMEOUT_SECONDS", "2"))
    qsm_status_path: str = os.getenv("QSM_STATUS_PATH", "/api/status")
    qsm_vitals_path: str = os.getenv("QSM_VITALS_PATH", "/api/vitals/read")
    qsm_camera_capture_path: str = os.getenv("QSM_CAMERA_CAPTURE_PATH", "/api/camera/capture")
    qsm_dispense_path: str = os.getenv("QSM_DISPENSE_PATH", "/api/dispense")
    local_camera_device: str = os.getenv("LOCAL_CAMERA_DEVICE", "/dev/video0")
    dispense_dry_run: bool = os.getenv("DISPENSE_DRY_RUN", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


settings = Settings()
