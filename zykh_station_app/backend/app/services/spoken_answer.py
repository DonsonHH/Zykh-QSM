from __future__ import annotations

import re


def compact_spoken_answer(text: str) -> str:
    return re.sub(r"[\s，。！？,.!?；;：:]", "", text or "")


def is_uncertain_answer(text: str) -> bool:
    compact = compact_spoken_answer(text)
    return any(
        term in compact
        for term in ("不知道", "不清楚", "不确定", "记不清", "不能明确", "无法确认")
    )


def is_contextual_negative_answer(text: str) -> bool:
    compact = compact_spoken_answer(text)
    if not compact or is_uncertain_answer(compact):
        return False
    if compact in {
        "没有",
        "还没有",
        "没",
        "无",
        "暂时没有",
        "没有啊",
        "没有的",
        "真没有",
        "真的没有",
        "确实没有",
    }:
        return True
    return any(
        term in compact
        for term in (
            "都没有",
            "都还没有",
            "什么都没有",
            "一个都没有",
            "没有任何",
            "我说没有",
        )
    )
