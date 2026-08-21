from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402


class ReleaseMetadataTest(unittest.TestCase):
    def test_openapi_reports_the_v2_release_version(self) -> None:
        self.assertEqual(create_app().version, "2.0.1")

    def test_frontend_package_and_lock_report_the_same_release(self) -> None:
        app_root = BACKEND_ROOT.parent
        package = json.loads((app_root / "frontend" / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((app_root / "frontend" / "package-lock.json").read_text(encoding="utf-8"))

        self.assertEqual(package["version"], "2.0.1")
        self.assertEqual(lock["version"], "2.0.1")
        self.assertEqual(lock["packages"][""]["version"], "2.0.1")


if __name__ == "__main__":
    unittest.main()
