from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import settings
from ..repositories.medicine_repository import MedicineRepository
from ..repositories.vitals_repository import VitalsRepository
from ..schemas.inquiry import InquiryEvaluateRequest


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

    def evaluate_inquiry(self, request: InquiryEvaluateRequest) -> dict[str, Any]:
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if settings.ai_mode == "local" or not key:
            return {"ok": False, "source": "local_fallback", "message": "未配置云端密钥，已使用本地规则兜底。"}

        payload = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": self._inquiry_system_prompt()},
                {"role": "user", "content": self._inquiry_user_prompt(request)},
            ],
            "temperature": 0.1,
            "max_tokens": 700,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        http_request = Request(
            settings.ai_api_base,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(http_request, timeout=18) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return self._evaluate_inquiry_via_qsm(request, f"主机云通道 HTTP {exc.code}")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return self._evaluate_inquiry_via_qsm(request, f"主机云通道暂不可用：{exc}")

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return self._evaluate_inquiry_via_qsm(request, "主机云通道结构化内容无法解析")
        if not isinstance(parsed, dict):
            return self._evaluate_inquiry_via_qsm(request, "主机云通道结构化内容为空")
        parsed["ok"] = True
        parsed["source"] = "cloud"
        parsed["message"] = "云通道已完成结构化分析。"
        return parsed

    def stream_chunks(self, message: str) -> list[str]:
        reply = self.chat(message)["reply"]
        return [reply[index : index + 18] for index in range(0, len(reply), 18)] or [""]

    def _local_reply(self, message: str, note: str) -> dict[str, Any]:
        text = message.strip() or "当前信息不足"
        reply = (
            f"{note} 已记录本次问题：{text[:80]}。"
            "本地兜底仅做风险提示和信息整理，不能替代医生诊断或处方；如有胸痛、呼吸困难、意识不清、高热不退等情况，请立即联系医生或救援人员。"
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
                "中高风险、禁忌不明或症状严重时，建议联系医生、家人或远程协助人员。",
                f"最近体征：{vitals_text}",
                f"家庭药柜药品：{medicine_text}",
            ]
        )

    def _inquiry_system_prompt(self) -> str:
        return "\n".join(
            [
                "你是偏远家庭弱网用药终端的 AI 应急问询助手，使用中文。",
                "你只能做健康信息整理、风险提示、药品信息匹配和禁忌核验，不能替代医生诊断或处方。",
                "不能输出“应该吃某药”；只能输出可查看候选药品类别和安全提示。",
                "中高风险、禁忌不明、症状严重或信息不足时，can_proceed_to_dispense 必须为 false。",
                "请只输出合法 JSON，不要输出 markdown。",
                "JSON 格式示例：{\"risk_level\":\"low\",\"risk_label\":\"低风险\",\"symptoms_summary\":\"...\",\"suggested_categories\":[\"感冒发热\"],\"contraindication_warnings\":[],\"safety_notice\":\"...\",\"next_steps\":[\"...\"],\"can_proceed_to_dispense\":true}",
            ]
        )

    def _inquiry_user_prompt(self, request: InquiryEvaluateRequest) -> str:
        medicines = MedicineRepository().list_all()
        latest_vitals = VitalsRepository().latest()
        medicine_text = [
            {
                "id": medicine.id,
                "name": medicine.name,
                "category": medicine.category,
                "slot": medicine.hardware_slot,
                "stock": medicine.stock,
                "unit": medicine.unit,
                "contraindications": medicine.contraindications,
                "is_otc": medicine.is_otc,
            }
            for medicine in medicines
            if medicine.stock > 0
        ]
        vitals = None
        if latest_vitals:
            vitals = {
                "temperature": latest_vitals.temperature,
                "heart_rate": latest_vitals.heart_rate,
                "spo2": latest_vitals.spo2,
                "measured_at": latest_vitals.measured_at,
            }
        return json.dumps(
            {
                "instruction": "请基于以下家庭成员自述、体征和家庭药柜库存做风险提示与药品信息匹配，输出 JSON。",
                "symptoms_text": request.symptoms_text,
                "duration": request.duration,
                "used_medicines": request.used_medicines,
                "allergy_or_contraindication": request.allergy_or_contraindication,
                "scene_type": request.scene_type,
                "include_vitals": request.include_vitals,
                "latest_vitals": vitals,
                "available_medicines": medicine_text,
            },
            ensure_ascii=False,
        )

    def _evaluate_inquiry_via_qsm(self, request: InquiryEvaluateRequest, reason: str) -> dict[str, Any]:
        if settings.qsm_mode != "real":
            return {"ok": False, "source": "local_fallback", "message": f"{reason}；已使用本地规则兜底。"}
        url = f"{settings.qsm_api_base}{settings.qsm_ai_chat_path if settings.qsm_ai_chat_path.startswith('/') else '/' + settings.qsm_ai_chat_path}"
        system_prompt = self._inquiry_system_prompt()
        user_prompt = self._inquiry_user_prompt(request)
        payload = {
            "message": f"{system_prompt}\n\n{user_prompt}",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        http_request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(http_request, timeout=22) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "source": "local_fallback", "message": f"{reason}；QSM 4G 云通道不可用：{exc}；已使用本地规则兜底。"}

        content = (
            data.get("reply")
            or data.get("content")
            or data.get("text")
            or data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        if isinstance(content, dict):
            parsed = dict(content)
        else:
            try:
                parsed = json.loads(str(content).strip())
            except json.JSONDecodeError:
                return {"ok": False, "source": "local_fallback", "message": f"{reason}；QSM 4G 云通道未返回结构化结果，已使用本地规则兜底。"}
        if not isinstance(parsed, dict):
            return {"ok": False, "source": "local_fallback", "message": f"{reason}；QSM 4G 云通道结果为空，已使用本地规则兜底。"}
        parsed["ok"] = True
        parsed["source"] = "qsm_cloud"
        parsed["message"] = "QSM 4G 云通道已完成结构化分析。"
        return parsed

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
