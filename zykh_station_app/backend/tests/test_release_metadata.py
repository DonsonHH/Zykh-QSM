from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402


class ReleaseMetadataTest(unittest.TestCase):
    def test_openapi_reports_the_v2_release_version(self) -> None:
        self.assertEqual(create_app().version, "2.0.0")


if __name__ == "__main__":
    unittest.main()
