from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import settings
from ..repositories.medicine_repository import MedicineRepository
from ..schemas.medicine import MedicineScanResult, MedicineVisualRecognizeResponse
from .local_camera import LocalCameraService


class MedicineScanService:
    def __init__(self, repository: MedicineRepository | None = None) -> None:
        self.repository = repository or MedicineRepository()

    def scan(self, manual_code: str | None = None) -> MedicineScanResult:
        if manual_code:
            return self._result_from_barcode(manual_code, None, "manual")

        capture = LocalCameraService().capture()
        if not capture.get("ok"):
            return MedicineScanResult(
                ok=False,
                status="camera_unavailable",
                image_path=capture.get("image_path"),
                error_message=capture.get("error_message") or "摄像头不可用。",
            )
        image_path = capture.get("image_path")
        barcode = self._decode_barcode(str(image_path)) if image_path else None
        if barcode:
            return self._result_from_barcode(barcode, str(image_path), "barcode")

        visual = self.visual_recognize(str(image_path) if image_path else None)
        if visual.barcode:
            return self._result_from_barcode(visual.barcode, str(image_path), visual.source)
        return MedicineScanResult(
            ok=False,
            status="manual_required",
            image_path=str(image_path) if image_path else None,
            source=visual.source,
            error_message=visual.error_message or "未识别到清晰条码或药盒信息，请人工核验。",
        )

    def visual_recognize(self, image_path: str | None) -> MedicineVisualRecognizeResponse:
        if not image_path or not Path(image_path).exists():
            return MedicineVisualRecognizeResponse(ok=False, source="vision", error_message="没有可识别的图片。")
        key = self._read_key()
        if not key:
            return MedicineVisualRecognizeResponse(ok=False, source="vision", error_message="未配置视觉识别密钥。")
        try:
            image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        except OSError as exc:
            return MedicineVisualRecognizeResponse(ok=False, source="vision", error_message=f"读取图片失败：{exc}")

        prompt = "请从图片中识别药盒名称、商品条码和有效期。只输出 JSON，字段为 name, barcode, expire_date。"
        payload = {
            "model": settings.qwen_vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                }
            ],
            "temperature": 0.1,
        }
        request = Request(
            settings.dashscope_api_base,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=25) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return MedicineVisualRecognizeResponse(ok=False, source="vision", error_message=f"视觉识别 HTTP {exc.code}")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return MedicineVisualRecognizeResponse(ok=False, source="vision", error_message=f"视觉识别失败：{exc}")

        raw_text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        parsed = self._parse_visual_text(raw_text)
        return MedicineVisualRecognizeResponse(
            ok=bool(parsed.get("barcode") or parsed.get("name") or parsed.get("expire_date")),
            source="vision",
            raw_text=raw_text,
            barcode=parsed.get("barcode"),
            name=parsed.get("name"),
            expire_date=parsed.get("expire_date"),
            error_message=None if parsed else "视觉识别未返回有效药品信息。",
        )

    def _result_from_barcode(self, barcode: str, image_path: str | None, source: str) -> MedicineScanResult:
        medicine = self.repository.get_by_barcode(barcode)
        if not medicine:
            return MedicineScanResult(
                ok=False,
                status="unknown_barcode",
                image_path=image_path,
                barcode=barcode,
                source=source,
                error_message="条码未匹配到站点药品，请人工核验。",
            )
        return MedicineScanResult(
            ok=True,
            status="matched",
            image_path=image_path,
            barcode=barcode,
            medicine_id=medicine.id,
            name=medicine.name,
            match_percent=99,
            spec=medicine.image_hint,
            quantity=f"{medicine.stock}{medicine.unit}",
            expire_date=medicine.expire_date,
            slot=medicine.slot,
            source=source,
        )

    def _decode_barcode(self, image_path: str) -> str | None:
        command = settings.medicine_scan_cmd
        if not command:
            found = shutil.which("zykh-scan-code") or shutil.which("zbarimg")
            if found:
                command = f"{found} {{image}}"
        if not command:
            return None
        try:
            result = subprocess.run(
                ["sh", "-c", command.format(image=image_path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = "\n".join([result.stdout or "", result.stderr or ""])
        json_payload = self._try_json(text)
        if isinstance(json_payload, dict):
            candidate = json_payload.get("code") or json_payload.get("barcode") or json_payload.get("text")
            if candidate:
                return str(candidate).strip()
        match = re.search(r"\b\d{8,14}\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _try_json(text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _parse_visual_text(text: str) -> dict[str, str]:
        if not text:
            return {}
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json\n", "", 1)
        parsed = MedicineScanService._try_json(cleaned)
        if isinstance(parsed, dict):
            return {key: str(value) for key, value in parsed.items() if value}
        result: dict[str, str] = {}
        barcode = re.search(r"\b\d{8,14}\b", text)
        expire = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})", text)
        if barcode:
            result["barcode"] = barcode.group(0)
        if expire:
            result["expire_date"] = expire.group(1).replace("年", "-").replace("月", "-").replace("/", "-").replace(".", "-")
        return result

    @staticmethod
    def _read_key() -> str:
        if settings.dashscope_api_key.strip():
            return settings.dashscope_api_key.strip()
        try:
            if settings.dashscope_api_key_file.exists():
                return settings.dashscope_api_key_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return ""
