from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.qsm_face_client import QsmFaceClient  # noqa: E402


class QsmFaceClientTest(unittest.TestCase):
    @patch("app.services.qsm_face_client.urlopen")
    def test_reads_bmp_frame_from_face_runtime(self, mocked_open) -> None:
        frame = b"BM" + b"\x00" * 128
        mocked_open.return_value = BytesIO(frame)

        result, error = QsmFaceClient().read_preview_frame()

        self.assertEqual(result, frame)
        self.assertIsNone(error)

    @patch("app.services.qsm_face_client.urlopen")
    def test_reports_waiting_while_first_face_frame_is_not_ready(self, mocked_open) -> None:
        mocked_open.side_effect = HTTPError(
            url="http://127.0.0.1:18081/api/face/frame",
            code=404,
            msg="waiting",
            hdrs=None,
            fp=BytesIO(b""),
        )

        result, error = QsmFaceClient().read_preview_frame()

        self.assertIsNone(result)
        self.assertEqual(error, "waiting")

    @patch("app.services.qsm_face_client.urlopen")
    def test_rejects_non_bmp_preview_payload(self, mocked_open) -> None:
        mocked_open.return_value = BytesIO(b"not-a-bitmap")

        result, error = QsmFaceClient().read_preview_frame()

        self.assertIsNone(result)
        self.assertIn("格式", error)


if __name__ == "__main__":
    unittest.main()
