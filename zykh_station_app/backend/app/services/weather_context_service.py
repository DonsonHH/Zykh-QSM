from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import settings


_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"expires_at": 0.0, "value": None}


class WeatherContextService:
    RELEVANT_TERMS = (
        "中暑",
        "暑热",
        "高温",
        "暴晒",
        "晒了",
        "闷热",
        "热得",
        "出汗",
        "脱水",
        "成都天气",
        "天气太热",
    )

    WEATHER_LABELS = {
        0: "晴",
        1: "大致晴朗",
        2: "局部多云",
        3: "阴",
        45: "有雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "毛毛雨",
        55: "较强毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        80: "阵雨",
        81: "较强阵雨",
        82: "强阵雨",
        95: "雷雨",
        96: "雷雨伴小冰雹",
        99: "雷雨伴冰雹",
    }

    def __init__(self, opener: Callable[..., Any] | None = None) -> None:
        self.opener = opener or urlopen

    def inquiry_context(
        self,
        transcript: str,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self._is_relevant(transcript, existing or {}):
            return None
        return self.current()

    def current(self) -> dict[str, Any] | None:
        now = time.monotonic()
        with _CACHE_LOCK:
            if _CACHE["value"] is not None and float(_CACHE["expires_at"]) > now:
                return dict(_CACHE["value"])

        query = urlencode(
            {
                "latitude": settings.inquiry_location_latitude,
                "longitude": settings.inquiry_location_longitude,
                "current": (
                    "temperature_2m,apparent_temperature,"
                    "relative_humidity_2m,weather_code"
                ),
                "timezone": "Asia/Shanghai",
            }
        )
        request = Request(
            f"{settings.weather_api_base}?{query}",
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "zykh-station/1.0"},
        )
        try:
            with self.opener(request, timeout=settings.weather_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

        current = payload.get("current")
        if not isinstance(current, dict):
            return None
        raw_weather_code = current.get("weather_code")
        try:
            weather_code = int(raw_weather_code)
        except (TypeError, ValueError):
            weather_code = -1
        result = {
            "location": settings.inquiry_location_name,
            "observed_at": str(current.get("time") or ""),
            "temperature_c": self._number(current.get("temperature_2m")),
            "apparent_temperature_c": self._number(current.get("apparent_temperature")),
            "relative_humidity_percent": self._number(current.get("relative_humidity_2m")),
            "weather": self.WEATHER_LABELS.get(weather_code, "天气状况未分类"),
            "source": "Open-Meteo",
            "usage_note": "仅作为环境背景，不可单独用于判断病因或替代体征测量。",
        }
        with _CACHE_LOCK:
            _CACHE["value"] = dict(result)
            _CACHE["expires_at"] = now + settings.weather_cache_seconds
        return result

    @classmethod
    def _is_relevant(cls, transcript: str, existing: dict[str, Any]) -> bool:
        fragments = [
            transcript,
            str(existing.get("case_summary") or ""),
            str(existing.get("symptoms_text") or ""),
        ]
        fragments.extend(
            str(item.get("content") or "")
            for item in existing.get("conversation") or []
            if isinstance(item, dict)
        )
        text = " ".join(fragments)
        return any(term in text for term in cls.RELEVANT_TERMS)

    @staticmethod
    def _number(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
