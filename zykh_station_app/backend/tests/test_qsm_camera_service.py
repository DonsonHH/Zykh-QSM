from __future__ import annotations

import sys
import threading
import tempfile
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.qsm_camera_service import QsmCameraService  # noqa: E402
from app.config import settings  # noqa: E402


class QsmCameraServiceTest(unittest.TestCase):
    def test_simulated_network_mode_uses_the_modem_free_health_route(self) -> None:
        response = BytesIO(b'{"ok":true}')
        with (
            patch(
                "app.services.qsm_camera_service.settings",
                replace(settings, network_demo_simulate=True),
            ),
            patch(
                "app.services.qsm_camera_service.urlopen",
                return_value=response,
            ) as mocked_open,
        ):
            status = QsmCameraService(base_url="http://qsm.invalid").capabilities()

        request = mocked_open.call_args.args[0]
        self.assertEqual(status, "available")
        self.assertEqual(request.full_url, "http://qsm.invalid/api/audio/status")
        self.assertNotIn("/api/status", request.full_url)

    def test_physical_network_mode_can_use_the_full_gateway_status_route(self) -> None:
        response = BytesIO(b'{"ok":true}')
        with (
            patch(
                "app.services.qsm_camera_service.settings",
                replace(settings, network_demo_simulate=False),
            ),
            patch(
                "app.services.qsm_camera_service.urlopen",
                return_value=response,
            ) as mocked_open,
        ):
            status = QsmCameraService(base_url="http://qsm.invalid").capabilities()

        request = mocked_open.call_args.args[0]
        self.assertEqual(status, "available")
        self.assertEqual(request.full_url, "http://qsm.invalid/api/status")

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

    def test_concurrent_streams_save_latest_frame_without_sharing_a_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            latest = Path(temp_dir) / "qsm-live-latest.jpg"
            services = [QsmCameraService(), QsmCameraService()]
            for service in services:
                service.capture_dir = Path(temp_dir)
                service.latest_path = latest

            barrier = threading.Barrier(2)
            original_write_bytes = Path.write_bytes

            def synchronized_write(path: Path, data: bytes) -> int:
                written = original_write_bytes(path, data)
                if path.suffix == ".tmp":
                    barrier.wait(timeout=2)
                return written

            errors: list[Exception] = []

            def save(service: QsmCameraService, image: bytes) -> None:
                try:
                    service._save_frame(image)
                except Exception as exc:  # pragma: no cover - assertion captures the race
                    errors.append(exc)

            with patch.object(Path, "write_bytes", new=synchronized_write):
                threads = [
                    threading.Thread(target=save, args=(services[0], b"first-frame")),
                    threading.Thread(target=save, args=(services[1], b"second-frame")),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)

            self.assertEqual(errors, [])
            self.assertIn(latest.read_bytes(), {b"first-frame", b"second-frame"})


if __name__ == "__main__":
    unittest.main()
