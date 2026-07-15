from __future__ import annotations

import json
import re
import socket
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .. import db
from ..config import settings
from ..repositories.medicine_repository import MedicineRepository
from ..repositories.vitals_repository import VitalsRepository
from ..schemas.inquiry import InquiryEvaluateRequest
from .local_ai_client import LocalAiClient


class AiService:
    EMERGENCY_TERMS = (
        "胸痛",
        "呼吸困难",
        "意识不清",
        "昏迷",
        "严重过敏",
        "无法呼吸",
        "口角歪斜",
        "单侧无力",
        "大量出血",
        "高热不退",
    )
    DIRECT_MEDICATION_PATTERN = re.compile(
        r"(?:你|患者)?(?:应该|应当|建议|可以|立即).{0,8}(?:服用|吃|使用).{0,24}(?:药|片|胶囊|颗粒|丸|口服液)"
    )
    DIAGNOSTIC_CLAIM_PATTERN = re.compile(
        r"(?:属于.{0,10}(?:症|病)|诊断为|可以排除|以排除|无需(?:紧急)?处理|基本确定|"
        r"考虑为.{0,10}(?:症|病)|可能(?:是|为|患有).{0,12}(?:症|病)|"
        r"(?:警惕|排除|考虑为).{0,16}(?:脑血管意外|脑供血不足|低血压|高血压|中风|脑梗|心梗|肺炎|感染|脱水))"
    )

    def __init__(self, local_client: LocalAiClient | None = None) -> None:
        self.local_client = local_client or LocalAiClient()

    def status(self) -> dict[str, Any]:
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        return {
            "ok": True,
            "mode": settings.ai_mode,
            "cloud_configured": bool(key),
            "cloud_model": settings.ai_model,
            "local": self.local_client.status(),
        }

    def warm_local(self) -> dict[str, Any]:
        status = self.local_client.status()
        if not status.get("ready"):
            return {
                "ok": False,
                "ready": False,
                "message": status.get("error_message") or "离线模型尚未就绪。",
            }
        result = self.local_client.chat(
            [
                {"role": "system", "content": self._local_system_prompt()},
                {
                    "role": "user",
                    "content": self._chat_user_prompt("请开始确认身份。", {}),
                },
            ],
            temperature=0.1,
            max_tokens=1,
        )
        return {
            "ok": bool(result.get("ok")),
            "ready": True,
            "message": "离线问询缓存已预热。" if result.get("ok") else result.get("error_message") or "预热失败。",
        }

    def chat(self, message: str) -> dict[str, Any]:
        message = message.strip()
        emergency = self._emergency_reply(message)
        if emergency:
            return emergency

        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if settings.ai_mode == "local" or self._network_local_mode():
            return self._local_model_reply(message, "当前为离线模式。")
        if not key:
            return self._local_model_reply(message, "未配置云端密钥。")
        if settings.ai_mode == "auto" and not self._cloud_reachable():
            return self._local_model_reply(message, "当前未检测到可用云端网络。")

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
        self._apply_provider_options(payload, enable_thinking=settings.ai_enable_thinking)
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
            with urlopen(request, timeout=settings.ai_chat_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return self._local_model_reply(message, f"云端通道 HTTP {exc.code}。")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return self._local_model_reply(message, f"云端通道暂不可用：{exc}。")

        reply = self._extract_message_text(data)
        if not reply:
            return self._local_model_reply(message, "云端通道未返回有效内容。")
        return {
            "ok": True,
            "source": "cloud",
            "model": settings.ai_model,
            "reply": self._guard_reply(reply, message),
            "offline": False,
        }

    def stream(self, message: str, context: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        message = message.strip()
        emergency = self._emergency_reply(message)
        if emergency:
            yield {"type": "meta", "source": emergency["source"], "model": emergency["model"]}
            yield {"type": "delta", "source": emergency["source"], "text": emergency["reply"]}
            yield {"type": "done", "source": emergency["source"], "reply": emergency["reply"]}
            return

        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        local_reason = ""
        if settings.ai_mode == "local" or self._network_local_mode():
            local_reason = "当前为离线模式。"
        elif not key:
            local_reason = "未配置云端密钥。"
        elif settings.ai_mode == "auto" and not self._cloud_reachable():
            local_reason = "当前未检测到可用云端网络。"
        if local_reason:
            yield from self._stream_local(message, context, local_reason)
            return

        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._chat_user_prompt(message, context)},
            ],
            "temperature": 0.2,
            "max_tokens": 180,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._apply_provider_options(payload, enable_thinking=settings.ai_enable_thinking)
        request = Request(
            settings.ai_api_base,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        try:
            response = urlopen(request, timeout=settings.ai_chat_timeout_seconds)
        except HTTPError as exc:
            yield from self._stream_local(message, context, f"云端通道 HTTP {exc.code}。")
            return
        except (URLError, TimeoutError, OSError) as exc:
            yield from self._stream_local(message, context, f"云端通道暂不可用：{exc}。")
            return

        yield {"type": "meta", "source": "cloud", "model": settings.ai_model}
        reply = ""
        try:
            with response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    value = line[5:].strip()
                    if value == "[DONE]":
                        break
                    try:
                        data = json.loads(value)
                    except json.JSONDecodeError:
                        continue
                    delta = LocalAiClient._delta_text(data)
                    if delta:
                        reply += delta
                        yield {"type": "delta", "source": "cloud", "text": delta}
        except OSError as exc:
            yield {"type": "error", "source": "cloud", "message": f"云端流式响应中断：{exc}"}
            return

        guarded = self._guard_stream_reply(reply, message)
        if guarded != reply.strip():
            yield {"type": "replace", "source": "cloud", "text": guarded}
        yield {"type": "done", "source": "cloud", "reply": guarded}

    def evaluate_inquiry(self, request: InquiryEvaluateRequest) -> dict[str, Any]:
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if settings.ai_mode == "local" or self._network_local_mode():
            return self._evaluate_inquiry_local(request, "当前为离线模式。")
        if not key:
            return self._evaluate_inquiry_local(request, "未配置云端密钥。")
        if settings.ai_mode == "auto" and not self._cloud_reachable():
            return self._evaluate_inquiry_local(request, "当前未检测到可用云端网络。")

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
        self._apply_provider_options(payload, enable_thinking=settings.ai_inquiry_enable_thinking)
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
            with urlopen(http_request, timeout=settings.ai_inquiry_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return self._evaluate_inquiry_local(request, f"主机云通道 HTTP {exc.code}。")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return self._evaluate_inquiry_local(request, f"主机云通道暂不可用：{exc}。")

        content = self._extract_message_text(data)
        parsed = self._parse_json_content(content)
        if parsed is None:
            return self._evaluate_inquiry_local(request, "主机云通道结构化内容无法解析。")
        if not isinstance(parsed, dict):
            return self._evaluate_inquiry_local(request, "主机云通道结构化内容为空。")
        parsed["ok"] = True
        parsed["source"] = "cloud"
        parsed["message"] = "云通道已完成结构化分析。"
        return parsed

    def stream_chunks(self, message: str) -> list[str]:
        reply = self.chat(message)["reply"]
        return [reply[index : index + 18] for index in range(0, len(reply), 18)] or [""]

    def _stream_local(
        self,
        message: str,
        context: dict[str, Any] | None,
        reason: str,
    ) -> Iterator[dict[str, Any]]:
        messages = [
            {"role": "system", "content": self._local_system_prompt()},
            {"role": "user", "content": self._chat_user_prompt(message, context)},
        ]
        yielded = False
        reply = ""
        for event in self.local_client.stream(messages, temperature=0.15, max_tokens=120):
            if event.get("type") == "delta":
                if not yielded:
                    yielded = True
                    yield {
                        "type": "meta",
                        "source": "local_llm",
                        "model": settings.local_ai_model,
                        "fallback_reason": reason,
                    }
                text = str(event.get("text") or "")
                reply += text
                yield {"type": "delta", "source": "local_llm", "text": text}
            elif event.get("type") == "error":
                rules = self._rules_reply(message, f"{reason}{event.get('message') or ''}")
                yield {"type": "meta", "source": rules["source"], "model": rules["model"]}
                yield {"type": "delta", "source": rules["source"], "text": rules["reply"]}
                yield {"type": "done", "source": rules["source"], "reply": rules["reply"]}
                return
        guarded = self._guard_stream_reply(reply, message)
        if not yielded:
            rules = self._rules_reply(message, f"{reason}离线模型未返回有效内容。")
            yield {"type": "meta", "source": rules["source"], "model": rules["model"]}
            yield {"type": "delta", "source": rules["source"], "text": rules["reply"]}
            yield {"type": "done", "source": rules["source"], "reply": rules["reply"]}
            return
        if guarded != reply.strip():
            yield {"type": "replace", "source": "local_llm", "text": guarded}
        yield {"type": "done", "source": "local_llm", "reply": guarded}

    def _local_model_reply(self, message: str, reason: str) -> dict[str, Any]:
        result = self.local_client.chat(
            [
                {"role": "system", "content": self._local_system_prompt()},
                {"role": "user", "content": message or "请先引导我说明现在最不舒服的地方。"},
            ],
            temperature=0.2,
            max_tokens=220,
        )
        if not result.get("ok"):
            detail = str(result.get("error_message") or "离线模型不可用")
            return self._rules_reply(message, f"{reason}{detail}")
        result["reply"] = self._guard_reply(str(result.get("reply") or ""), message)
        result.pop("raw", None)
        result["fallback_reason"] = reason
        return result

    def _rules_reply(self, message: str, note: str) -> dict[str, Any]:
        text = (message.strip() or "当前信息不足").rstrip("。！？!?")
        reply = (
            f"离线模型暂不可用，安全规则已记录：{text[:80]}。"
            "请继续补充症状、持续时间、已用药和过敏禁忌；如有胸痛、呼吸困难、意识不清或高热不退，请立即联系医生或救援人员。"
        )
        return {
            "ok": True,
            "source": "rules_fallback",
            "model": "safety-rules",
            "reply": reply,
            "offline": True,
            "fallback_reason": note,
        }

    def _system_prompt(self) -> str:
        return "\n".join(
            [
                "你是智药康护终端的 AI应急问询助手，使用中文。",
                "你只能做健康信息整理、风险提示、药品信息匹配和禁忌核验，不能替代医生诊断或处方。",
                "不能说用户应该吃某药；只能提示可查看候选药品类别和安全提示。",
                "不能判断用户属于轻症或无需处理，不能猜测病因；每次只追问一个缺失信息。",
                "按顺序核对症状、持续时间、已用药、过敏禁忌和体征；一次只问一个缺失项。",
                "终端当前只稳定读取体温、心率和血氧；需要体征时只引导这三项，不要求血压或HRV。",
                "缺少体征时在简短回复末尾加 [NEED_VITALS]；信息完整且无紧急危险信号时加 [READY_FOR_SAFETY_ANALYSIS]。",
                "不要罗列药柜库存；候选药品必须留到结构化安全核验阶段。",
                "中高风险、禁忌不明或症状严重时，建议联系医生、家人或远程协助人员。",
                "回复控制在 45 个中文字符内，不要 Markdown，不要编号列表，不输出思考过程。",
            ]
        )

    @staticmethod
    def _local_system_prompt() -> str:
        return "\n".join(
            [
                "你是家庭康护终端的安全问询助手，只用中文。",
                "不诊断、不下处方、不直接指令服药。",
                "依次确认身份、症状、持续时间、已用药、禁忌和体征；每次只问一项。",
                "体征只询问体温、心率、血氧，不询问血压或HRV。",
                "缺体征加[NEED_VITALS]；信息完整且无紧急信号加[READY_FOR_SAFETY_ANALYSIS]。",
                "胸痛、呼吸困难或意识不清时立即提示求助。",
                "回复不超过45字，不列清单，不输出思考过程。",
            ]
        )

    @staticmethod
    def _chat_user_prompt(message: str, context: dict[str, Any] | None = None) -> str:
        context = context if isinstance(context, dict) else {}
        profile = context.get("profile") if isinstance(context.get("profile"), dict) else {}
        profile_text = "/".join(
            str(value).strip()
            for value in (
                profile.get("name"),
                f"{profile.get('age')}岁" if profile.get("age") else "",
                profile.get("conditions"),
                f"禁忌:{profile.get('allergies')}" if profile.get("allergies") else "",
            )
            if str(value or "").strip()
        )
        transcript = str(context.get("transcript") or "").strip()[-180:]
        vitals = str(context.get("vitals") or "").strip()[:100]
        return json.dumps(
            {
                "使用人": profile_text or "待确认",
                "体征": vitals or "未测量",
                "已知自述": transcript or "暂无",
                "本轮输入": message,
            },
            ensure_ascii=False,
            separators=(",", ":"),
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

    def _inquiry_user_prompt(self, request: InquiryEvaluateRequest, compact: bool = False) -> str:
        medicines = MedicineRepository().list_all()
        latest_vitals = VitalsRepository().latest_for_context() if request.include_vitals else None
        if compact:
            medicine_text = [
                {
                    "name": medicine.name,
                    "category": medicine.category,
                    "slot": medicine.hardware_slot,
                    "is_otc": medicine.is_otc,
                }
                for medicine in medicines
                if medicine.stock > 0
            ]
        else:
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
                "systolic_pressure": latest_vitals.systolic_pressure,
                "diastolic_pressure": latest_vitals.diastolic_pressure,
                "respiratory_rate": latest_vitals.respiratory_rate,
                "hrv_sdnn": latest_vitals.hrv_sdnn,
                "hrv_rmssd": latest_vitals.hrv_rmssd,
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

    def _evaluate_inquiry_local(self, request: InquiryEvaluateRequest, reason: str) -> dict[str, Any]:
        system_prompt = self._inquiry_system_prompt()
        user_prompt = self._inquiry_user_prompt(request, compact=True)
        result = self.local_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=520,
            response_format={"type": "json_object"},
        )
        if not result.get("ok"):
            detail = str(result.get("error_message") or "离线模型不可用")
            return {
                "ok": False,
                "source": "rules_fallback",
                "message": f"{reason}离线模型不可用：{detail}；已由安全规则继续核验。",
            }
        parsed = self._parse_json_content(str(result.get("reply") or ""))
        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "source": "rules_fallback",
                "message": f"{reason}离线模型未返回可解析的结构化结果；已由安全规则继续核验。",
            }
        parsed["ok"] = True
        parsed["source"] = "local_llm"
        parsed["message"] = f"{reason}QSM 离线模型已完成结构化分析。"
        parsed["offline"] = True
        return parsed

    def _emergency_reply(self, message: str) -> dict[str, Any] | None:
        if not message or not any(self._has_unnegated_term(message, term) for term in self.EMERGENCY_TERMS):
            return None
        return {
            "ok": True,
            "source": "safety_rules",
            "model": "safety-rules",
            "reply": "检测到可能的紧急风险。请停止自行取药，立即联系医生、急救人员或现场值守人员，并保持有人陪同。",
            "offline": True,
        }

    def _guard_reply(self, reply: str, user_message: str = "") -> str:
        text = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL | re.IGNORECASE).strip()
        if not text:
            return "目前信息不足，请继续说明症状、持续时间、已用药和过敏禁忌。"
        if self.DIRECT_MEDICATION_PATTERN.search(text):
            return (
                "我已整理当前信息，但不能直接给出服药指令。"
                "请先完成禁忌核验，可查看候选药品类别和安全提示；处方药需按已有医嘱使用。"
            )
        if self.DIAGNOSTIC_CLAIM_PATTERN.search(text):
            context = "已记录你的描述。" if user_message else "已记录当前信息。"
            return (
                f"{context}我不能判断病因或确认风险等级。"
                f"{self._safe_followup(user_message)}若症状加重，请联系医生或家人协助。"
            )
        if any(self._has_unnegated_term(text, term) for term in self.EMERGENCY_TERMS) and not any(
            phrase in text for phrase in ("立即联系", "立即就医", "急救")
        ):
            text = f"{text} 如出现或持续存在上述危险信号，请立即联系医生或急救人员。"
        return self._compact_chat_reply(text)

    def _guard_stream_reply(self, reply: str, user_message: str = "") -> str:
        markers = "".join(
            marker for marker in ("[NEED_VITALS]", "[READY_FOR_SAFETY_ANALYSIS]") if marker in reply
        )
        clean = reply.replace("[NEED_VITALS]", "").replace("[READY_FOR_SAFETY_ANALYSIS]", "").strip()
        guarded = self._guard_reply(clean, user_message)
        return f"{guarded}{markers}"

    @staticmethod
    def _compact_chat_reply(text: str) -> str:
        normalized = re.sub(r"\s+", "", text).strip()
        normalized = (
            normalized.replace("上述列出的任何药物", "任何药物")
            .replace("上述任何药品", "任何药物")
            .replace("上述药品", "这些药物")
        )
        question_count = normalized.count("？") + normalized.count("?")
        if len(normalized) > 100 or question_count > 1:
            question = AiService._first_complete_question(normalized)
            if question:
                return question
        if len(normalized) <= 100:
            return normalized
        return f"{normalized[:96]}…"

    @staticmethod
    def _first_complete_question(text: str) -> str:
        endings = [index for index in (text.find("？"), text.find("?")) if index >= 0]
        if not endings:
            return ""
        prefix = text[: min(endings) + 1]
        start = max(prefix.rfind(mark) for mark in ("。", "；", ";", "：", ":"))
        question = prefix[start + 1 :].strip()
        question = re.sub(r"^\d+[.、)]", "", question).strip()
        if len(question) > 90:
            trigger_positions = [
                position
                for trigger in ("请问", "请确认", "请说明", "请补充")
                if (position := question.rfind(trigger)) >= 0
            ]
            if trigger_positions:
                question = question[max(trigger_positions) :]
        return question if 2 < len(question) <= 90 else ""

    @staticmethod
    def _safe_followup(user_message: str) -> str:
        message = user_message or ""
        if any(term in message for term in ("咳嗽", "流涕", "鼻塞", "咽痛")):
            return "请继续说明症状持续多久，是否伴有发热或呼吸费力；"
        if any(term in message for term in ("头晕", "头痛", "站不稳", "视物")):
            return "请继续说明是否伴有恶心、视物模糊或站立不稳；"
        if any(term in message for term in ("腹泻", "胃痛", "腹痛", "呕吐")):
            return "请继续说明症状持续多久、次数，以及能否正常饮水；"
        if any(term in message for term in ("过敏", "瘙痒", "皮疹", "红肿")):
            return "请继续说明皮肤变化范围，以及是否伴有面唇肿胀或呼吸不适；"
        if any(term in message for term in ("擦伤", "外伤", "破皮", "出血")):
            return "请继续说明伤口位置、大小及是否仍在出血；"
        return "请继续说明症状持续时间、严重程度、已用药和过敏禁忌；"

    @staticmethod
    def _has_unnegated_term(text: str, term: str) -> bool:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                return False
            prefix = text[max(0, index - 8) : index]
            if not re.search(r"(?:没有|并无|无|否认|未出现|不伴)(?:任何|明显)?$", prefix):
                return True
            start = index + len(term)

    @staticmethod
    def _cloud_reachable() -> bool:
        parsed = urlparse(settings.ai_api_base)
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=settings.ai_connectivity_timeout_seconds):
                return True
        except OSError:
            return False

    @staticmethod
    def _network_local_mode() -> bool:
        return db.get_setting("network_mode", settings.network_preferred_mode).strip().lower() in {"local", "offline"}

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

    @staticmethod
    def _apply_provider_options(payload: dict[str, Any], enable_thinking: bool) -> None:
        api_base = settings.ai_api_base.lower()
        if "deepseek.com" in api_base:
            payload["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
            if enable_thinking:
                payload["reasoning_effort"] = "high"
                payload.pop("temperature", None)
            return
        if enable_thinking:
            payload["enable_thinking"] = True

    @staticmethod
    def _extract_message_text(data: dict[str, Any]) -> str:
        choice = (data.get("choices") or [{}])[0] if isinstance(data.get("choices"), list) else {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            content = "".join(parts)
        text = str(content or "").strip()
        if text:
            return text
        reasoning = message.get("reasoning_content") or choice.get("delta", {}).get("reasoning_content")
        return str(reasoning or "").strip()

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any] | None:
        text = (content or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None
