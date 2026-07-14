from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.repositories.vitals_repository import VitalsRecord, VitalsRepository  # noqa: E402


class VitalsRepositoryTest(unittest.TestCase):
    def test_latest_for_context_ignores_newer_failed_attempt(self) -> None:
        original_path = settings.db_path
        with tempfile.TemporaryDirectory() as temp_dir:
            object.__setattr__(settings, "db_path", Path(temp_dir) / "station.db")
            try:
                repository = VitalsRepository()
                repository.append(
                    VitalsRecord(
                        id="valid",
                        temperature=36.4,
                        heart_rate=74,
                        spo2=98,
                        status="available",
                        source="real",
                        measured_at="2026-07-14 10:00:00",
                    )
                )
                repository.append(
                    VitalsRecord(
                        id="failed",
                        status="unavailable",
                        source="unavailable",
                        error_message="sensor timeout",
                        measured_at="2026-07-14 10:01:00",
                    )
                )

                latest = repository.latest_for_context()
            finally:
                object.__setattr__(settings, "db_path", original_path)

        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, "valid")


if __name__ == "__main__":
    unittest.main()
