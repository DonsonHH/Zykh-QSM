from __future__ import annotations

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services import weather_context_service as weather_module  # noqa: E402
from app.services.weather_context_service import WeatherContextService  # noqa: E402


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class WeatherContextServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        weather_module._CACHE["expires_at"] = 0.0
        weather_module._CACHE["value"] = None

    def test_weather_is_loaded_only_for_environment_related_complaints(self) -> None:
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(
                json.dumps(
                    {
                        "current": {
                            "time": "2026-07-20T14:00",
                            "temperature_2m": 34.2,
                            "apparent_temperature": 38.7,
                            "relative_humidity_2m": 72,
                            "weather_code": 2,
                        }
                    }
                ).encode("utf-8")
            )

        service = WeatherContextService(opener=opener)

        self.assertIsNone(service.inquiry_context("膝盖擦伤了", {}))
        result = service.inquiry_context("在外面晒了以后像是中暑，有点头晕", {})

        self.assertEqual(result["location"], "成都")
        self.assertEqual(result["apparent_temperature_c"], 38.7)
        self.assertIn("不可单独用于判断病因", result["usage_note"])
        self.assertEqual(len(requests), 1)
        query = parse_qs(urlparse(requests[0][0].full_url).query)
        self.assertEqual(query["timezone"], ["Asia/Shanghai"])
        self.assertIn("apparent_temperature", query["current"][0])

    def test_cached_weather_avoids_repeated_network_requests(self) -> None:
        calls = 0

        def opener(_request, timeout):
            nonlocal calls
            calls += 1
            return FakeResponse(
                b'{"current":{"time":"now","temperature_2m":33,'
                b'"apparent_temperature":36,"relative_humidity_2m":60,"weather_code":0}}'
            )

        service = WeatherContextService(opener=opener)
        service.inquiry_context("疑似中暑", {})
        service.inquiry_context("天气太热了", {})

        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
