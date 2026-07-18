from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FacePreviewContractTest(unittest.TestCase):
    def test_face_runtime_exports_atomic_bmp_preview_frames(self) -> None:
        source = (ROOT / "qsm_gateway" / "src" / "qsm_face.c").read_text(encoding="utf-8")

        self.assertIn("QSM_FACE_PREVIEW_BMP", source)
        self.assertIn("write_preview_bmp", source)
        self.assertIn("rename(temporary, path)", source)

    def test_face_gateway_serves_runtime_owned_preview(self) -> None:
        gateway = (ROOT / "qsm_gateway" / "face_gateway.pl").read_text(encoding="utf-8")

        self.assertIn("/api/face/frame", gateway)
        self.assertIn("QSM_FACE_PREVIEW_BMP", gateway)
        self.assertIn("image/bmp", gateway)


if __name__ == "__main__":
    unittest.main()
