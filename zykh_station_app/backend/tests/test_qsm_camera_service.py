from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.qsm_camera_service import QsmCameraService  # noqa: E402


class QsmCameraServiceTest(unittest.TestCase):
    def test_extract_latest_complete_jpeg_and_keep_partial_tail(self) -> None:
        first = b"\xff\xd8first\xff\xd9"
        second = b"\xff\xd8second\xff\xd9"
        partial = b"\xff\xd8partial"

        frame, tail = QsmCameraService.extract_latest_jpeg(b"headers" + first + b"boundary" + second + partial)

        self.assertEqual(frame, second)
        self.assertEqual(tail, partial)

    @patch("app.services.qsm_camera_service.time.sleep")
    @patch("app.services.qsm_camera_service.urlopen")
    def test_open_stream_retries_transient_gateway_error(self, mocked_open, mocked_sleep) -> None:
        transient = HTTPError(
            url="http://127.0.0.1:18080/api/camera/stream",
            code=500,
            msg="camera restarting",
            hdrs=None,
            fp=BytesIO(b'{"error":"camera restarting"}'),
        )
        response = BytesIO(b"--zykhframe")
        response.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=zykhframe"}
        mocked_open.side_effect = [transient, response]

        stream, content_type, error = QsmCameraService().open_stream()

        self.assertIs(stream, response)
        self.assertIn("multipart/x-mixed-replace", content_type)
        self.assertIsNone(error)
        self.assertEqual(mocked_open.call_count, 2)
        mocked_sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
