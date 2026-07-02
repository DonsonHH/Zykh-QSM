from __future__ import annotations

import json
import os
from typing import Any, Iterator

import httpx

from .ai import ai_api_key
from .config import (
    AI_API_BASE,
    AI_CLOUD_TIMEOUT_SECONDS,
    AI_MODEL,
    LOCAL_AI_BASE_URL,
    LOCAL_AI_MODEL,
    LOCAL_AI_PROVIDER,
    LOCAL_AI_TIMEOUT_SECONDS,
)

SAFETY_NOTICE = "本系统仅提供应急辅助信息和药品匹配参考，不能替代医生诊断、处方或专业救援判断。如出现严重症状，请立即联系医生、管理员或救援人员。"

EMERGENCY_KEYWORDS = ["胸痛", "呼吸困难", "昏迷", "意识不清", "抽搐", "大出血", "严重过敏", "喉头水肿", "单侧无力"]
HIGH_KEYWORDS = ["高热", "剧烈", "持续呕吐", "便血", "血压", "严重头晕", "外伤", "骨折"]
MEDIUM_KEYWORDS = ["发热", "腹泻", "呕吐", "过敏", "皮疹", "头晕", "疼痛"]

CATEGORY_RULES = [
    ("感冒发热", ["发热", "咳嗽", "咽痛", "流涕", "感冒", "高热"]),
    ("肠胃", ["腹泻", "腹痛", "呕吐", "胃", "恶心"]),
    ("过敏", ["过敏", "皮疹", "瘙痒", "红肿"]),
    ("外伤消毒", ["外伤", "擦伤", "出血", "消毒"]),
    ("高原/晕动", ["高原", "晕车", "晕动", "缺氧"]),
    ("慢病常用", ["高血压", "糖尿病", "慢病", "血压"]),
]


def normalize_mode(mode: str | None) -> str:
    value = (mode or "").strip().lower()
    return value if value in {"online", "weak", "offline"} else "weak"


def risk_from_text(text: str) -> str:
    if any(word in text for word in EMERGENCY_KEYWORDS):
        return "emergency"
    if any(word in text for word in HIGH_KEYWORDS):
        return "high"
    if any(word in text for word in MEDIUM_KEYWORDS):
        return "medium"
    return "low"


def categories_from_text(text: str) -> list[str]:
    got = [category for category, words in CATEGORY_RULES if any(word in text for word in words)]
    return got or ["其他应急"]


def medicine_matches(categories: list[str], medicines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for med in medicines:
        if int(med.get("stock") or 0) <= 0:
            continue
        haystack = " ".join(
            str(med.get(key) or "")
            for key in ("category", "indication_tags", "name", "safety_note", "contraindications")
        )
        if any(category in haystack for category in categories):
            matches.append(
                {
                    "slot": med.get("slot"),
                    "name": med.get("name", ""),
                    "category": med.get("category", ""),
                    "stock": med.get("stock", 0),
                    "unit": med.get("unit", "件"),
                    "contraindications": med.get("contraindications", ""),
                    "safety_note": med.get("safety_note", ""),
                }
            )
    return matches[:5]


def rules_triage(payload: dict[str, Any], context: dict[str, Any], provider: str = "rules") -> dict[str, Any]:
    symptoms = str(payload.get("symptoms_text") or payload.get("message") or "").strip()
    allergies = str(payload.get("allergy_or_contraindication") or "").strip()
    profile = context.get("profile") or {}
    medicines = context.get("medicines") or []
    risk_level = risk_from_text(symptoms + " " + allergies)
    categories = categories_from_text(symptoms)
    candidates = medicine_matches(categories, medicines)
    contraindication_hit = bool(allergies) or any(
        allergies and allergies in str(item.get("contraindications") or "") for item in candidates
    )
    allow_self_confirm = risk_level == "low" and bool(candidates) and not contraindication_hit
    need_admin_review = not allow_self_confirm
    warnings = [
        "AI 不开药、不诊断、不生成处方，只提供应急辅助问询、药品辅助匹配、风险提示和用药安全核验。",
        "请核对过敏史、禁忌、重复用药和药品说明书。",
    ]
    if allergies:
        warnings.append(f"已记录过敏/禁忌提示：{allergies}。")
    if risk_level in {"medium", "high", "emergency"}:
        warnings.append("当前风险等级需要管理员复核；如症状明显或加重，请联系医生或救援人员。")
    if not candidates:
        warnings.append("当前库存未匹配到明确可用药品，请联系管理员人工核验。")

    next_steps = [
        "先补充症状持续时间、年龄、既往疾病和已用药情况。",
        "可读取体征并将结果交给管理员复核。",
    ]
    if allow_self_confirm:
        next_steps.append("低风险且库存可用，可进入用户取药确认；取药前仍需核对说明书和禁忌。")
    else:
        next_steps.append("暂不建议自助取药，请请求管理员复核或联系医生/救援人员。")

    summary = symptoms or "尚未输入症状"
    action_summary = "低风险可进入取药确认" if allow_self_confirm else "需要管理员复核或联系医生/救援"
    return {
        "ok": True,
        "provider": provider,
        "ai_mode": provider if provider in {"rules", "mock"} else "local",
        "risk_level": risk_level,
        "symptoms_summary": summary[:120],
        "suggested_categories": categories,
        "candidate_medicines": candidates,
        "safety_warnings": warnings,
        "next_steps": next_steps,
        "need_admin_review": need_admin_review,
        "allow_self_confirm": allow_self_confirm,
        "action_summary": action_summary,
        "safety_notice": SAFETY_NOTICE,
        "profile_context": {
            "name": profile.get("name", ""),
            "conditions": profile.get("conditions", ""),
            "allergies": profile.get("allergies", ""),
        },
    }


def triage_markdown(result: dict[str, Any]) -> str:
    candidates = result.get("candidate_medicines") or []
    candidate_text = "、".join(
        f"{item.get('name')}({item.get('slot')}号仓，余{item.get('stock')}{item.get('unit','件')})"
        for item in candidates
        if item.get("name")
    ) or "暂未匹配到明确库存药品"
    warnings = "；".join(result.get("safety_warnings") or [])
    next_steps = "；".join(result.get("next_steps") or [])
    return (
        f"风险等级：{risk_label(result.get('risk_level'))}\n\n"
        f"症状摘要：{result.get('symptoms_summary') or '未填写'}\n\n"
        f"候选药品类别：{'、'.join(result.get('suggested_categories') or [])}\n\n"
        f"当前库存匹配：{candidate_text}\n\n"
        f"禁忌提醒：{warnings}\n\n"
        f"后续建议：{next_steps}\n\n"
        f"安全声明：{result.get('safety_notice') or SAFETY_NOTICE}"
    )


def risk_label(value: str | None) -> str:
    return {
        "low": "低",
        "medium": "中",
        "high": "高",
        "emergency": "紧急",
    }.get(value or "", "待评估")


def stream_chunks(text: str, size: int = 24) -> Iterator[str]:
    for i in range(0, len(text), size):
        yield text[i : i + size]


def call_ollama(prompt: str) -> str:
    url = f"{LOCAL_AI_BASE_URL}/api/generate"
    payload = {"model": os.getenv("LOCAL_AI_MODEL", LOCAL_AI_MODEL), "prompt": prompt, "stream": False}
    with httpx.Client(timeout=LOCAL_AI_TIMEOUT_SECONDS, trust_env=False) as client:
        res = client.post(url, json=payload)
        res.raise_for_status()
        data = res.json()
    return str(data.get("response") or "").strip()


def local_ai_health() -> dict[str, Any]:
    provider = os.getenv("LOCAL_AI_PROVIDER", LOCAL_AI_PROVIDER).strip().lower() or "rules"
    base_url = os.getenv("LOCAL_AI_BASE_URL", LOCAL_AI_BASE_URL).rstrip("/")
    model = os.getenv("LOCAL_AI_MODEL", LOCAL_AI_MODEL)
    if provider in {"rules", "mock"}:
        return {
            "ok": True,
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "fallback": "rules",
            "detail": "当前使用规则兜底，不依赖本地模型服务。",
        }
    try:
        with httpx.Client(timeout=LOCAL_AI_TIMEOUT_SECONDS, trust_env=False) as client:
            if provider == "ollama":
                res = client.get(f"{base_url}/api/tags")
                res.raise_for_status()
                data = res.json()
                names = [str(item.get("name", "")) for item in data.get("models", [])]
                available = model in names or any(name.startswith(f"{model}:") for name in names)
                return {
                    "ok": available,
                    "provider": provider,
                    "base_url": base_url,
                    "model": model,
                    "fallback": "rules" if not available else "",
                    "detail": "本地模型可用" if available else "Ollama 可访问，但未发现配置的模型；问询会自动切换规则兜底。",
                    "models": names[:12],
                }
            if provider == "llamacpp":
                res = client.get(f"{base_url}/health")
                if res.status_code == 404:
                    res = client.get(f"{base_url}/v1/models")
                return {
                    "ok": res.is_success,
                    "provider": provider,
                    "base_url": base_url,
                    "model": model,
                    "fallback": "" if res.is_success else "rules",
                    "detail": "llama.cpp 服务可访问" if res.is_success else "llama.cpp 服务不可用，问询会自动切换规则兜底。",
                    "status_code": res.status_code,
                }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "fallback": "rules",
            "detail": f"本地 AI 不可用，问询会自动切换规则兜底：{exc}",
        }
    return {
        "ok": False,
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "fallback": "rules",
        "detail": "不支持的本地 AI provider，问询会自动切换规则兜底。",
    }


def call_local_ai(prompt: str, provider: str) -> str:
    if provider == "mock":
        return ""
    if provider == "ollama":
        return call_ollama(prompt)
    if provider == "llamacpp":
        url = f"{LOCAL_AI_BASE_URL}/completion"
        with httpx.Client(timeout=LOCAL_AI_TIMEOUT_SECONDS, trust_env=False) as client:
            res = client.post(url, json={"prompt": prompt, "n_predict": 420})
            res.raise_for_status()
            data = res.json()
        return str(data.get("content") or data.get("response") or "").strip()
    raise RuntimeError(f"unsupported local provider: {provider}")


def call_cloud_ai(prompt: str) -> str:
    key = ai_api_key()
    if not key:
        raise RuntimeError("cloud AI key not configured")
    payload = {
        "model": os.getenv("AI_MODEL", AI_MODEL),
        "messages": [
            {"role": "system", "content": "你是智药康护应急辅助问询助手。必须保守、安全、不能诊断、不能开药、不能生成处方。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 520,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=AI_CLOUD_TIMEOUT_SECONDS, trust_env=False) as client:
        res = client.post(os.getenv("AI_API_BASE", AI_API_BASE), headers=headers, json=payload)
        res.raise_for_status()
        data = res.json()
    return str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()


def build_triage_prompt(payload: dict[str, Any], context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "请基于以下信息进行应急辅助问询和药品辅助匹配。",
            "严禁诊断、开药、处方或承诺疗效。必须提示过敏、禁忌、重复用药和人工复核。",
            "输出包含：风险等级、症状总结、候选药品类别、库存匹配、禁忌提醒、后续建议、安全声明。",
            "",
            "输入：",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "",
            "上下文：",
            json.dumps(context, ensure_ascii=False, indent=2),
            "",
            f"固定安全声明：{SAFETY_NOTICE}",
        ]
    )


def route_triage(payload: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    network_mode = normalize_mode(payload.get("network_mode") or (context.get("site") or {}).get("network_mode"))
    provider = os.getenv("LOCAL_AI_PROVIDER", LOCAL_AI_PROVIDER).strip().lower() or "rules"
    base = rules_triage(payload, context, provider="rules")
    prompt = build_triage_prompt(payload, context)
    ai_text = ""
    used_provider = "rules"
    if network_mode == "online":
        try:
            ai_text = call_cloud_ai(prompt)
            used_provider = "cloud"
        except Exception:
            try:
                ai_text = call_local_ai(prompt, provider)
                used_provider = provider
            except Exception:
                used_provider = "rules"
    elif network_mode == "weak":
        try:
            ai_text = call_cloud_ai(prompt)
            used_provider = "cloud"
        except Exception:
            try:
                ai_text = call_local_ai(prompt, provider)
                used_provider = provider
            except Exception:
                used_provider = "rules"
    else:
        try:
            ai_text = call_local_ai(prompt, provider)
            used_provider = provider
        except Exception:
            used_provider = "rules"

    result = {**base, "provider": used_provider, "ai_mode": "cloud" if used_provider == "cloud" else ("rules" if used_provider == "rules" else "local")}
    if ai_text:
        result["model_text"] = ai_text
        text = ai_text
        if SAFETY_NOTICE not in text:
            text = f"{text}\n\n安全声明：{SAFETY_NOTICE}"
    else:
        text = triage_markdown(result)
    return result, text
