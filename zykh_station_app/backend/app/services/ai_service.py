from __future__ import annotations

import json
import logging
import re
import socket
import time
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .. import db
from ..config import settings
from .local_ai_client import LocalAiClient


logger = logging.getLogger(__name__)


class AiService:
    LOCAL_INQUIRY_DIMENSIONS = {
        "cold": "感冒鼻部症状",
        "fever": "发热全身不适",
        "cough": "咳嗽咳痰",
        "throat": "咽喉口腔不适",
        "summer": "恶心暑湿",
        "diarrhea": "腹泻肠道不适",
        "constipation": "便秘",
        "stomach": "胃酸胃部不适",
        "allergy": "过敏瘙痒",
        "wound": "轻微外伤",
        "fungus": "皮肤真菌不适",
        "pain": "肌肉关节疼痛",
        "eye": "干眼不适",
        "rhinitis": "鼻炎过敏",
        "supplement": "营养补充",
        "chronic": "慢病既往用药",
    }
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
                {"role": "system", "content": self._local_inquiry_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "known": {"s": "symptoms", "t": 0, "d": [], "du": "", "u": "", "a": "", "v": False},
                            "profile": {"age": 0, "history": "", "allergy": ""},
                            "said": "你好",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=1,
            response_format={"type": "json_object"},
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

    def extract_inquiry_information(
        self,
        transcript: str,
        existing: dict[str, Any],
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Build an open, evidence-grounded case state without choosing medicine."""
        system_prompt = (
            "你是家庭康护终端的中文问询医师助理。你负责自然问询、病例理解和语义风险判断，"
            "但不能替代医生诊断或处方，不能选择药品、仓位或控制任何硬件。只输出一个 JSON 对象。"
            "不要套用症状分类白名单；observations.concept 应按用户真实表达自由概括。"
            "每条 observation 必须含 status=present|absent|uncertain、用户原话 evidence、"
            "原话所在 source_turn 和 confidence。不得把否定表达写成 present。"
            "完整阅读 conversation、profile、vitals 和 recent_history；历史只用于比较，"
            "不得直接复用上次结论。每轮只问一个真正影响理解或安全的缺失信息，禁止固定字段顺序和重复追问。"
            "next_action 只能是 ask、measure_vitals、analyze、escalate、end。"
            "先从用户原话中形成明确主诉；主诉尚未明确时不得选择 measure_vitals。"
            "主诉明确后，如果额温、心率和血氧会实质影响下一步判断，选择 measure_vitals；"
            "不要按固定轮数触发，也不要为了收集数据而测量。信息足够时选择 analyze；"
            "出现明显危险信号时选择 escalate。risk_level 只能是 low、medium、high、emergency。"
            "assistant_reply 是直接给用户的一句自然回应；ask 时包含一个问题；"
            "measure_vitals 时用一句自然中文解释为什么本次需要测量，不要继续追问。"
            "history_relationship.should_reuse_previous_conclusion 必须为 false。"
        )
        user_prompt = json.dumps(
            {
                "current_utterance": transcript,
                "case_state": existing,
                "person": profile,
                "output_contract": {
                    "case_summary": "",
                    "observations": [
                        {
                            "concept": "",
                            "status": "present",
                            "evidence": "",
                            "source_turn": 1,
                            "confidence": 0.0,
                        }
                    ],
                    "uncertainties": [],
                    "history_relationship": {
                        "related": False,
                        "similarities": [],
                        "important_changes": [],
                        "should_reuse_previous_conclusion": False,
                    },
                    "duration": "",
                    "used_medicines": "",
                    "allergy_or_contraindication": "",
                    "next_action": "ask",
                    "next_question": "",
                    "assistant_reply": "",
                    "reason": "",
                    "risk_level": "low",
                    "risk_signals": [],
                    "confidence": 0.0,
                },
            },
            ensure_ascii=False,
        )
        if settings.ai_mode == "local" or self._network_local_mode():
            return self._extract_inquiry_local(transcript, existing, profile, "当前为离线模式。")
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key:
            return self._extract_inquiry_local(transcript, existing, profile, "未配置云端密钥。")
        if settings.ai_mode == "auto" and not self._cloud_reachable():
            return self._extract_inquiry_local(transcript, existing, profile, "云端网络不可用。")

        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.15,
            "max_tokens": 900,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        self._apply_provider_options(payload, enable_thinking=False)
        parsed, cloud_error = self._request_json_completion(
            payload,
            key,
            purpose="inquiry_extract",
        )
        if not isinstance(parsed, dict):
            return self._extract_inquiry_local(
                transcript,
                existing,
                profile,
                f"云端问询失败：{cloud_error or '未返回有效结构'}。",
            )
        return {"ok": True, "source": "cloud", **parsed}

    def rank_inquiry_candidates(
        self,
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Let AI rank only IDs already admitted by the deterministic safety pool."""
        if not candidates:
            return {"ok": True, "source": "safety_pool", "options": []}
        system_prompt = (
            "你是家庭康护问询的候选药品排序助手。程序已完成库存、有效期、OTC资格和绝对禁忌过滤。"
            "你只能从 candidates 中选择，不能新增药品、改变字段或控制药柜。"
            "结合病例、个人信息、体征和药品说明决定是否存在合适候选；不合适可返回空 options。"
            "最多输出一个主方案和一个备选方案，备选不是联合服用；证据明确时只给主方案。"
            "每个方案最多三个药品，只有确需按顺序完成的护理组合才可包含多个药品。"
            "reason 用一至两句自然中文说明推荐原因，不使用‘覆盖症状、库存核验、独立备选、互斥’等程序语言。"
            "只输出 JSON：{\"summary\":\"\",\"options\":[{\"option_id\":\"primary\","
            "\"label\":\"主方案\",\"reason\":\"\",\"medicine_ids\":[\"\"]}]}。"
        )
        user_prompt = json.dumps(
            {"case": context, "candidates": candidates},
            ensure_ascii=False,
        )
        if settings.ai_mode == "local" or self._network_local_mode():
            return self._rank_inquiry_candidates_local(system_prompt, user_prompt, "")
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key or (settings.ai_mode == "auto" and not self._cloud_reachable()):
            return self._rank_inquiry_candidates_local(
                system_prompt,
                user_prompt,
                "云端排序不可用。",
            )
        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 700,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        self._apply_provider_options(payload, enable_thinking=False)
        parsed, cloud_error = self._request_json_completion(
            payload,
            key,
            purpose="inquiry_rank",
        )
        return (
            {"ok": True, "source": "cloud", **parsed}
            if isinstance(parsed, dict)
            else self._rank_inquiry_candidates_local(
                system_prompt,
                user_prompt,
                f"云端排序失败：{cloud_error or '未返回有效结构'}。",
            )
        )

    def _rank_inquiry_candidates_local(
        self,
        system_prompt: str,
        user_prompt: str,
        reason: str,
    ) -> dict[str, Any]:
        result = self.local_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=320,
            response_format={"type": "json_object"},
        )
        if not result.get("ok"):
            return {"ok": False, "source": "ai_unavailable", "message": reason}
        parsed = self._parse_json_content(str(result.get("reply") or ""))
        if not isinstance(parsed, dict):
            return {"ok": False, "source": "ai_unavailable", "message": reason}
        return {"ok": True, "source": "local_llm", **parsed}

    def generate_inquiry_recommendation(self, context: dict[str, Any]) -> dict[str, Any]:
        """Explain already-approved options without allowing the model to alter them."""
        option_ids = [
            str(option.get("option_id") or "").strip()
            for option in context.get("options") or []
            if isinstance(option, dict) and str(option.get("option_id") or "").strip()
        ]
        if not option_ids:
            return {"ok": False, "source": "assistant"}

        system_prompt = (
            "你是家庭康护终端的中文沟通助手。候选方案已经由本地安全程序确定，你不能新增、删除、"
            "替换或重新排序药品，也不能改变风险等级。请根据用户原话、体征和每个方案中已经给出的"
            "药品说明，为用户写自然、易懂的推荐理由。不要复述程序字段，不要说‘覆盖症状’、‘库存核验’、"
            "‘独立备选’或‘互斥方案’，不要声称诊断结果。summary 用一至两句概括当前情况；"
            "option_reasons 必须逐个使用给定 option_id，每项一至两句，说明这个方案为什么更贴近当前情况、"
            "与其他方案的侧重点有什么不同。不得使用‘见效快’、‘快速缓解’、‘一定有效’、‘可以治好’等疗效承诺；"
            "用‘更贴近’、‘侧重于’或‘可对照说明’表达。只能输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "case": {
                    "user_name": context.get("user_name") or "访客",
                    "reasoning_summary": context.get("reasoning_summary") or "",
                    "symptom_dimensions": context.get("symptom_dimensions") or [],
                    "symptom_evidence": context.get("symptom_evidence") or {},
                    "duration": context.get("duration") or "",
                    "used_medicines": context.get("used_medicines") or "",
                    "allergy_or_contraindication": context.get("allergy_or_contraindication") or "",
                    "vitals": context.get("vitals") or {},
                    "risk_level": context.get("risk_level") or "",
                },
                "options": context.get("options") or [],
                "output": {
                    "summary": "面向用户的一至两句自然概括",
                    "option_reasons": {option_id: "该方案的自然推荐理由" for option_id in option_ids},
                },
            },
            ensure_ascii=False,
        )
        if settings.ai_mode == "local" or self._network_local_mode():
            return self._generate_recommendation_local(system_prompt, user_prompt, option_ids, "")
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key or (settings.ai_mode == "auto" and not self._cloud_reachable()):
            return self._generate_recommendation_local(
                system_prompt,
                user_prompt,
                option_ids,
                "云端当前不可用。",
            )

        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.35,
            "max_tokens": 520,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        self._apply_provider_options(payload, enable_thinking=False)
        parsed, cloud_error = self._request_json_completion(
            payload,
            key,
            purpose="inquiry_explain",
        )
        if not isinstance(parsed, dict):
            return self._generate_recommendation_local(
                system_prompt,
                user_prompt,
                option_ids,
                f"云端说明生成失败：{cloud_error or '未返回有效结构'}。",
            )
        return self._normalize_recommendation_language(parsed, option_ids, "cloud")

    def _generate_recommendation_local(
        self,
        system_prompt: str,
        user_prompt: str,
        option_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        result = self.local_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            max_tokens=240,
            response_format={"type": "json_object"},
        )
        if not result.get("ok"):
            return {"ok": False, "source": "assistant", "message": reason}
        parsed = self._parse_json_content(str(result.get("reply") or ""))
        normalized = self._normalize_recommendation_language(parsed, option_ids, "local_llm")
        if reason:
            normalized["fallback_reason"] = reason
        return normalized

    @classmethod
    def _normalize_recommendation_language(
        cls,
        payload: dict[str, Any] | None,
        option_ids: list[str],
        source: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"ok": False, "source": "assistant"}
        raw_reasons = payload.get("option_reasons")
        raw_reasons = raw_reasons if isinstance(raw_reasons, dict) else {}
        reasons = {
            option_id: cls._sanitize_recommendation_text(raw_reasons.get(option_id), 120)
            for option_id in option_ids
            if cls._sanitize_recommendation_text(raw_reasons.get(option_id), 120)
        }
        summary = cls._sanitize_recommendation_text(payload.get("summary"), 180)
        if not summary and not reasons:
            return {"ok": False, "source": "assistant"}
        return {
            "ok": True,
            "source": source,
            "summary": summary,
            "option_reasons": reasons,
        }

    @staticmethod
    def _compact_text(value: object, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text[:limit]

    @classmethod
    def _sanitize_recommendation_text(cls, value: object, limit: int) -> str:
        text = cls._compact_text(value, limit * 2)
        replacements = {
            "见效快": "更便于对照当前不适",
            "快速缓解": "侧重缓解",
            "一定有效": "可结合说明书核对",
            "可以治好": "可用于缓解相关不适",
            "保证有效": "可结合说明书核对",
        }
        for unsafe, neutral in replacements.items():
            text = text.replace(unsafe, neutral)
        return cls._compact_text(text, limit)

    def generate_inquiry_opening(self, user_name: str, has_profile: bool) -> dict[str, Any]:
        """Generate one conversational opening without letting the model control workflow."""
        if settings.ai_mode == "local" or self._network_local_mode():
            return {"ok": False, "source": "assistant"}
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key or not self._cloud_reachable():
            return {"ok": False, "source": "assistant"}

        system_prompt = (
            "你是家庭康护终端的中文问询助手。只生成一句自然、温和的开场问句，"
            "邀请用户说出今天哪里不舒服。不要说已读取资料，不要诊断、推荐药品或解释规则；"
            "不要 Markdown，不超过45个中文字符。"
        )
        user_prompt = json.dumps(
            {"称呼": user_name if user_name != "访客" else "", "已有基础档案": bool(has_profile)},
            ensure_ascii=False,
        )
        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.45,
            "max_tokens": 80,
            "stream": False,
        }
        self._apply_provider_options(payload, enable_thinking=False)
        request = Request(
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
            with urlopen(request, timeout=min(float(settings.ai_inquiry_timeout_seconds), 3.2)) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return {"ok": False, "source": "assistant"}

        reply = re.sub(r"[\r\n\"“”]", "", self._extract_message_text(data)).strip()
        if (
            not reply
            or len(reply) > 72
            or not any(term in reply for term in ("不舒服", "哪里", "哪儿", "感觉"))
            or any(term in reply for term in ("诊断", "处方", "推荐药", "已读取"))
        ):
            return {"ok": False, "source": "assistant"}
        return {"ok": True, "source": "cloud", "reply": reply}

    def _extract_inquiry_local(
        self,
        transcript: str,
        existing: dict[str, Any],
        profile: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        system_prompt = self._local_inquiry_system_prompt()
        compact_existing = {
            "t": int(existing.get("conversation_turns") or 0),
            "s": str(existing.get("case_summary") or "")[:140],
            "f": [
                {
                    "c": str(item.get("concept") or "")[:40],
                    "s": str(item.get("status") or "")[:10],
                    "e": str(item.get("evidence") or "")[:70],
                    "t": int(item.get("source_turn") or 0),
                }
                for item in existing.get("observations") or []
                if isinstance(item, dict)
            ][:12],
            "u": list(existing.get("uncertainties") or [])[:6],
            "du": str(existing.get("duration") or "")[:40],
            "m": str(existing.get("used_medicines") or "")[:60],
            "a": str(existing.get("allergy_or_contraindication") or "")[:60],
            "v": existing.get("vitals") or {},
            "h": list(existing.get("recent_history") or [])[:4],
            "c": [
                {
                    "r": str(message.get("role") or "")[:1],
                    "x": str(message.get("content") or "")[:100],
                }
                for message in existing.get("conversation") or []
                if isinstance(message, dict)
            ],
        }
        compact_profile = {
            "age": profile.get("age") or 0,
            "history": str(profile.get("profile") or "")[:80],
            "allergy": str(profile.get("allergies") or "")[:60],
        }
        user_prompt = json.dumps(
            {"known": compact_existing, "profile": compact_profile, "said": transcript},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        result = self.local_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=96,
            response_format={"type": "json_object"},
        )
        if not result.get("ok"):
            return {"ok": False, "source": "ai_unavailable", "message": reason}
        parsed = self._parse_json_content(str(result.get("reply") or ""))
        if not isinstance(parsed, dict):
            return {"ok": False, "source": "ai_unavailable", "message": reason}
        return {"ok": True, "source": "local_llm", **self._expand_local_inquiry(parsed)}

    @classmethod
    def _local_inquiry_system_prompt(cls) -> str:
        return (
            "你是家庭健康问询助手，不诊断、不选药、不控制硬件。仅输出单行JSON："
            "s=病例摘要；f=[[自由概念,present|absent|uncertain,用户原话,轮次,置信度]]；"
            "u=不确定项数组；du=持续时间；m=已用药；a=过敏禁忌；"
            "n=ask|measure_vitals|analyze|escalate|end；q=下一问；r=给用户的自然回复；"
            "k=low|medium|high|emergency；g=风险信号数组；c=0到1。"
            "先读known.c和known.h，不重复已回答问题；每轮最多问一件真正影响安全或理解的事。"
            "先形成明确主诉；只有体征会实质影响判断时才用measure_vitals，不按固定轮数触发。"
            "概念按用户实际表达自由概括，证据来自用户对话。历史只比较，不复用旧结论。"
        )

    @classmethod
    def _expand_local_inquiry(cls, payload: dict[str, Any]) -> dict[str, Any]:
        if "observations" in payload:
            return payload
        observations: list[dict[str, Any]] = []
        raw_facts = payload.get("f") if isinstance(payload.get("f"), list) else []
        for item in raw_facts:
            if isinstance(item, dict):
                concept = str(item.get("concept") or item.get("c") or "").strip()
                status = str(item.get("status") or item.get("s") or "uncertain").strip()
                evidence = str(item.get("evidence") or item.get("e") or "").strip()
                source_turn = item.get("source_turn") or item.get("t") or 0
                confidence = item.get("confidence") or item.get("p") or 0
            elif isinstance(item, list) and item:
                concept = str(item[0] or "").strip()
                status = str(item[1] if len(item) > 1 else "uncertain").strip()
                evidence = str(item[2] if len(item) > 2 else "").strip()
                source_turn = item[3] if len(item) > 3 else 0
                confidence = item[4] if len(item) > 4 else 0
            else:
                continue
            if not concept:
                continue
            observations.append(
                {
                    "concept": concept,
                    "status": status,
                    "evidence": evidence,
                    "source_turn": source_turn,
                    "confidence": confidence,
                }
            )
        return {
            "case_summary": str(payload.get("s") or "").strip(),
            "observations": observations,
            "uncertainties": payload.get("u") if isinstance(payload.get("u"), list) else [],
            "history_relationship": payload.get("h") if isinstance(payload.get("h"), dict) else {},
            "duration": str(payload.get("du") or "").strip(),
            "used_medicines": str(payload.get("m") or "").strip(),
            "allergy_or_contraindication": str(payload.get("a") or "").strip(),
            "next_question": str(payload.get("q") or "").strip(),
            "assistant_reply": str(payload.get("r") or payload.get("q") or "").strip(),
            "reason": str(payload.get("x") or "").strip(),
            "next_action": str(payload.get("n") or "ask").strip(),
            "risk_level": str(payload.get("k") or "low").strip(),
            "risk_signals": payload.get("g") if isinstance(payload.get("g"), list) else [],
            "confidence": payload.get("c") or 0,
        }

    def generate_medicine_guidance(self, medicine: dict[str, Any]) -> dict[str, Any]:
        """Generate structured reference text without presenting it as verified prescribing data."""
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if settings.ai_mode == "local" or self._network_local_mode():
            return {"ok": False, "error_message": "当前为本地模式，未调用云端药品资料补全。"}
        if not key:
            return {"ok": False, "error_message": "未配置云端密钥，药品资料保持待核对状态。"}
        if not self._cloud_reachable():
            return {"ok": False, "error_message": "云端网络暂不可用，药品资料保持待核对状态。"}

        system_prompt = "\n".join(
            [
                "你是家庭用药终端的药品说明资料整理助手。",
                "只整理公开药品说明中的适用症状、用法用量、禁忌提醒和安全提示，不诊断、不下处方。",
                "给定信息不足以确认剂型、规格或人群剂量时，不得猜测；用法用量必须写明以实物包装说明书或既往医嘱为准。",
                "不要声称已经联网检索、已经核验或来源于某份说明书，因为当前请求没有提供可验证的外部检索结果。",
                "只输出合法 json 对象，不要 Markdown。",
                "JSON 格式：{\"indications\":\"适用症状或用途\",\"dosage\":\"用法用量\",\"contraindications\":[\"禁忌1\",\"禁忌2\"],\"safety_note\":\"简短安全提示\"}",
            ]
        )
        user_prompt = json.dumps(
            {
                "instruction": "请根据基础信息生成简洁中文 json；每个文本字段不超过120字，禁忌2至5条。",
                "medicine": {
                    "name": str(medicine.get("name") or ""),
                    "manufacturer": str(medicine.get("manufacturer") or ""),
                    "barcode": str(medicine.get("barcode") or ""),
                    "category": str(medicine.get("category") or ""),
                },
            },
            ensure_ascii=False,
        )
        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 700,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        self._apply_provider_options(payload, enable_thinking=False)
        request = Request(
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
            with urlopen(request, timeout=settings.ai_inquiry_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return {"ok": False, "error_message": f"云端药品资料补全 HTTP {exc.code}。"}
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error_message": f"云端药品资料补全失败：{exc}。"}

        parsed = self._parse_json_content(self._extract_message_text(data))
        if not isinstance(parsed, dict):
            return {"ok": False, "error_message": "云端未返回可解析的药品资料。"}
        return {"ok": True, "source": "cloud_ai", "guidance": parsed}

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

    def _request_json_completion(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        purpose: str,
    ) -> tuple[dict[str, Any] | None, str]:
        max_attempts = max(1, min(int(settings.ai_inquiry_max_attempts), 3))
        attempt_timeout = max(
            2.0,
            min(
                float(settings.ai_inquiry_attempt_timeout_seconds),
                float(settings.ai_inquiry_timeout_seconds),
            ),
        )
        retry_delay = max(0.0, min(float(settings.ai_inquiry_retry_delay_seconds), 2.0))
        errors: list[str] = []
        retryable_http_codes = {408, 409, 425, 429, 500, 502, 503, 504}

        for attempt in range(1, max_attempts + 1):
            request = Request(
                settings.ai_api_base,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            retryable = True
            try:
                with urlopen(request, timeout=attempt_timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                parsed = self._parse_json_content(self._extract_message_text(data))
                if isinstance(parsed, dict):
                    return parsed, ""
                choice = (
                    (data.get("choices") or [{}])[0]
                    if isinstance(data.get("choices"), list)
                    else {}
                )
                finish_reason = str(choice.get("finish_reason") or "").strip()
                errors.append(
                    "返回内容被截断"
                    if finish_reason == "length"
                    else "返回结构无法解析"
                )
            except HTTPError as exc:
                retryable = exc.code in retryable_http_codes
                errors.append(f"HTTP {exc.code}")
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                errors.append(self._compact_error(exc))

            if not retryable or attempt >= max_attempts:
                break
            if retry_delay:
                time.sleep(retry_delay * attempt)

        error = "；".join(dict.fromkeys(errors)) or "未知错误"
        logger.warning("AI structured completion failed purpose=%s error=%s", purpose, error)
        return None, error

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
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                parsed, _end = decoder.raw_decode(text[match.start() :])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _compact_error(exc: BaseException) -> str:
        detail = re.sub(r"\s+", " ", str(exc or "")).strip()
        if isinstance(exc, TimeoutError) or "timed out" in detail.lower():
            return "读取超时"
        if isinstance(exc, json.JSONDecodeError):
            return "响应不是有效 JSON"
        return detail[:120] or exc.__class__.__name__
