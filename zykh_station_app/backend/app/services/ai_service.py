from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import settings
from ..repositories.medicine_repository import MedicineRepository
from ..repositories.vitals_repository import VitalsRepository


class AiService:
    def chat(self, message: str) -> dict[str, Any]:
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if settings.ai_mode == "local" or not key:
            return self._local_reply(message, "未配置云端密钥，已使用本地兜底。")

        payload = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": message},
            ],
            "temperature": 0.25,
            "max_tokens": 360,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            settings.ai_api_base,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=18) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return self._local_reply(message, f"云端通道 HTTP {exc.code}，已使用本地兜底。")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return self._local_reply(message, f"云端通道暂不可用：{exc}。已使用本地兜底。")

        reply = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not reply:
            return self._local_reply(message, "云端通道未返回有效内容，已使用本地兜底。")
        return {"ok": True, "source": "cloud", "model": settings.ai_model, "reply": reply}

    def stream_chunks(self, message: str) -> list[str]:
        reply = self.chat(message)["reply"]
        return [reply[index : index + 18] for index in range(0, len(reply), 18)] or [""]

    def _local_reply(self, message: str, note: str) -> dict[str, Any]:
        text = message.strip() or "当前信息不足"
        reply = (
            f"{note} 已记录本次问题：{text[:80]}。"
            "本地兜底仅做风险提示和信息整理，不能替代医生诊断或处方；如有胸痛、呼吸困难、意识不清、高热不退等情况，请立即联系医生或现场值守人员。"
        )
        return {"ok": True, "source": "local_fallback", "model": "rules-fallback", "reply": reply}

    def _system_prompt(self) -> str:
        medicines = MedicineRepository().list_all()
        latest_vitals = VitalsRepository().latest()
        medicine_text = "；".join(
            f"{medicine.name}({medicine.category}, 库存{medicine.stock}{medicine.unit})"
            for medicine in medicines[:12]
        ) or "暂无药品库存"
        vitals_text = "暂无体征记录"
        if latest_vitals:
            vitals_text = (
                f"体温{latest_vitals.temperature or '--'}℃，"
                f"心率{latest_vitals.heart_rate or '--'}次/分，"
                f"血氧{latest_vitals.spo2 or '--'}%，"
                f"时间{latest_vitals.measured_at}"
            )
        return "\n".join(
            [
                "你是智药康护终端的 AI应急问询助手，使用中文。",
                "你只能做健康信息整理、风险提示、药品信息匹配和禁忌核验，不能替代医生诊断或处方。",
                "不能说用户应该吃某药；只能提示可查看候选药品类别和安全提示。",
                "中高风险、禁忌不明或症状严重时，建议联系医生、村医或现场值守人员。",
                f"最近体征：{vitals_text}",
                f"站点药品：{medicine_text}",
            ]
        )

    @staticmethod
    def _read_key(value: str, path) -> str:
        if value.strip():
            return value.strip()
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return ""
