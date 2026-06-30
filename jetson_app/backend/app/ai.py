from __future__ import annotations

import json
import os
from typing import Any, Iterator

import httpx

from .config import AI_API_BASE, AI_KEY_FILE, AI_MODEL


def ai_api_key() -> str:
    key = os.getenv("AI_API_KEY", "").strip()
    if key:
        return key
    if AI_KEY_FILE.exists():
        return AI_KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


def build_system_prompt(context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "你是“智药康护”Jetson 主控终端中的 AI 问诊助手，使用中文回答。",
            "你的职责是解释健康知识、结合老人档案和最近体征给出风险提醒、提醒按医嘱用药。",
            "你不是医生，不能替代诊断，不能开处方，不能建议自行新增、停用或调整处方药剂量。",
            "药柜库存只代表家中现有药品，不能因为药柜里有某种药就建议直接服用。",
            "遇到胸痛、呼吸困难、意识障碍、严重过敏、单侧肢体无力、血压持续超过 180/110 mmHg 等情况，必须建议立即就医或急救。",
            "回答要适合老人听：先给一句结论，再给 3 到 4 条做法，最后说明何时就医。总长度 140 到 240 个中文字符。",
            "",
            "【本机上下文】",
            json.dumps(context, ensure_ascii=False, indent=2),
        ]
    )


def stream_chat(message: str, context: dict[str, Any]) -> Iterator[str]:
    key = ai_api_key()
    if not key:
        fallback = "AI 接口还没有配置密钥。当前可以先查看档案、体征和药柜上下文；配置 AI_API_KEY 后即可进行真实问诊。"
        for i in range(0, len(fallback), 12):
            yield fallback[i : i + 12]
        return

    payload = {
        "model": os.getenv("AI_MODEL", AI_MODEL),
        "messages": [
            {"role": "system", "content": build_system_prompt(context)},
            {"role": "user", "content": message},
        ],
        "temperature": 0.25,
        "max_tokens": 420,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.stream("POST", os.getenv("AI_API_BASE", AI_API_BASE), headers=headers, json=payload, timeout=60.0) as res:
        res.raise_for_status()
        for line in res.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if delta:
                yield delta

