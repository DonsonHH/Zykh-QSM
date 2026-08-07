from __future__ import annotations

import re
from typing import Iterable

from ..schemas.inquiry import InquiryExtractedInformation


MAX_SYMPTOM_FOLLOWUPS = 4

SYMPTOM_QUESTION_TOPICS = frozenset(
    {
        "main_symptom",
        "onset",
        "fever",
        "breathing",
        "headache_onset",
        "headache_red_flags",
        "severity",
        "respiratory_features",
        "throat_features",
        "digestive_features",
        "stool_features",
        "dehydration",
        "urinary_features",
        "skin_features",
        "injury_features",
        "exposure_trigger",
        "symptom_detail",
    }
)

QUESTION_TOPICS = SYMPTOM_QUESTION_TOPICS | {
    "additional_symptoms",
    "used_medicines",
    "allergy_or_contraindication",
    "none",
}

_SCOPE_COMPLETE_PHRASES = (
    "没有其他", "没有别的", "没其他", "没别的", "别的没有", "其他没有",
    "就这些", "只有这些", "就这一个", "只有这个", "除此之外没有", "其他都正常",
)

_UNKNOWN_EVIDENCE = (
    "不知道",
    "不清楚",
    "不确定",
    "没量",
    "没有量",
    "未测",
    "记不清",
)

_ROUTINE_MOBILITY_QUESTION_TERMS = (
    "能否站立",
    "可以站立",
    "正常站立",
    "能否行走",
    "可以行走",
    "正常行走",
    "走路不稳",
    "站立不稳",
    "站不稳",
    "走路是否受影响",
)

_TOPIC_QUESTIONS = {
    "main_symptom": "现在最不舒服的具体是什么？",
    "onset": "这种不舒服是从什么时候开始的？",
    "fever": "你现在量到的体温是多少度？如果还没量，直接说还没量就可以。",
    "breathing": "现在呼吸会觉得费力吗？",
    "headache_onset": "这次头痛是突然达到最痛，还是逐渐出现的？",
    "headache_red_flags": "头痛时，有没有一边手脚突然使不上力？",
    "severity": "现在最难受的感觉是轻微、明显，还是很严重？",
    "respiratory_features": "目前呼吸道不适中最明显的是哪一种表现？",
    "throat_features": "吞咽时嗓子痛会明显加重吗？",
    "digestive_features": "现在最明显的胃肠道不适是什么？",
    "stool_features": "大便里有没有血或呈黑色？",
    "dehydration": "现在喝水后能正常留住吗？",
    "urinary_features": "排尿时最明显的不适是什么？",
    "skin_features": "皮肤变化目前主要是什么样子？",
    "injury_features": "受伤部位现在能正常活动吗？",
    "exposure_trigger": "这次不适是在高温日晒或剧烈活动后出现的吗？",
    "symptom_detail": "在已经说到的不适中，目前最影响你的具体表现是什么？",
}

_TOPIC_TERMS = {
    "main_symptom": ("最不舒服", "哪里不舒服", "什么不舒服", "主要症状"),
    "onset": ("什么时候", "开始", "多久", "持续", "多长时间"),
    "fever": ("发热", "发烧", "体温", "发冷", "怕冷"),
    "breathing": ("呼吸", "胸闷", "气短", "喘", "憋气"),
    "headache_onset": ("头痛", "头疼", "突然", "最痛", "撞到头", "外伤"),
    "headache_red_flags": ("说话", "单侧", "无力", "麻木", "视物", "颈部", "走路"),
    "severity": ("严重", "多重", "影响", "活动", "几分"),
    "respiratory_features": ("咳嗽", "咳痰", "流鼻涕", "鼻塞", "呼吸道", "声音"),
    "throat_features": ("嗓子", "咽", "吞咽", "沙哑", "喉咙"),
    "digestive_features": ("恶心", "呕吐", "腹", "胃", "反酸", "烧心"),
    "stool_features": ("大便", "排便", "便血", "黑色", "腹泻"),
    "dehydration": ("喝水", "补水", "口干", "尿量", "脱水", "留住"),
    "urinary_features": ("排尿", "小便", "尿频", "尿急", "尿痛"),
    "skin_features": ("皮肤", "皮疹", "红疹", "瘙痒", "红肿"),
    "injury_features": ("伤口", "受伤", "出血", "活动", "肿胀"),
    "exposure_trigger": ("高温", "日晒", "暴晒", "闷热", "剧烈活动"),
    "symptom_detail": ("具体表现", "最明显", "最影响", "什么感觉"),
}

_BROAD_DETAIL_TOPICS = {
    "respiratory_features",
    "throat_features",
    "digestive_features",
    "urinary_features",
    "skin_features",
    "injury_features",
    "symptom_detail",
}

_DETAIL_FACT_GROUPS = (
    ("吞咽", "咽口水"),
    ("沙哑", "声音嘶哑"),
    ("咳嗽", "咳痰"),
    ("流鼻涕", "鼻塞", "打喷嚏"),
    ("恶心", "呕吐"),
    ("腹痛", "胃痛"),
    ("出血", "止血"),
    ("深", "表皮", "伤口深度"),
    ("红肿", "瘙痒", "皮疹"),
)


def compact_text(value: object, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_question_topic(value: object) -> str:
    topic = compact_text(value, 60).lower()
    return topic if topic in QUESTION_TOPICS else ""


def symptom_scope_explicitly_complete(transcript: str) -> bool:
    text = compact_text(transcript, 300)
    return bool(text and any(phrase in text for phrase in _SCOPE_COMPLETE_PHRASES))


def symptom_scope_confirmation_question(extracted: InquiryExtractedInformation) -> str:
    complaint = _dedupe_symptom_display(
        compact_text(extracted.symptoms_text or extracted.case_summary, 70)
    )
    if complaint:
        return f"目前我记录到{complaint}。除此之外，现在还有其他明显不舒服吗？"
    return "为了把情况了解完整，现在还有其他明显不舒服吗？"


def _dedupe_symptom_display(complaint: str) -> str:
    """Remove display-only aliases without making any clinical inference."""
    parts = [item.strip() for item in re.split(r"[、,，/；;]", complaint) if item.strip()]
    if len(parts) < 2:
        return complaint
    seen: set[str] = set()
    result: list[str] = []
    for item in parts:
        key = item.replace("嗓子", "咽").replace("咽喉", "咽")
        key = key.replace("疼痛", "痛").replace("头疼", "头痛")
        key = key.replace("声音嘶哑", "声音沙哑")
        key = re.sub(r"\s+", "", key)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return "、".join(result)


def normalize_answered_topics(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            topic
            for topic in (normalize_question_topic(item) for item in value)
            if topic and topic != "none"
        )
    )


def normalize_topic_evidence(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for raw_topic, raw_evidence in value.items():
        topic = normalize_question_topic(raw_topic)
        evidence = compact_text(raw_evidence, 180)
        if topic and topic != "none" and evidence:
            result[topic] = evidence
    return result


def independent_question_slot_count(reply: str) -> int:
    normalized = compact_text(reply, 900)
    strong_markers = re.findall(
        r"有没有|是否|什么时候|多长时间|多久|多少(?:度|次|天|小时)?|"
        r"哪(?:里|个|种|些)|为什么|怎么(?:样)?|什么(?:时候|地方|感觉|表现|药)?|"
        r"会不会|能不能",
        normalized,
    )
    embedded_ma = re.findall(r"吗(?=\s*[,，;；])", normalized)
    listed_features = re.findall(
        r"发热|发冷|咳嗽|咳痰|咽痛|嗓子痛|鼻塞|流鼻涕|全身酸痛|"
        r"恶心|呕吐|腹痛|腹泻|便血|黑便|乏力|出汗|胸闷|气短|呼吸费力|"
        r"视物异常|说话含糊|单侧无力|颈部僵硬|走路不稳",
        normalized,
    )
    bundled_slots = 2 if len(set(listed_features)) >= 3 else 0
    clinical_topic_groups = (
        ("发热", "发烧", "体温", "发冷", "怕冷"),
        ("呼吸费力", "胸闷", "气短", "喘", "憋气"),
        ("恶心", "想吐", "呕吐", "腹泻", "腹痛", "胃痛"),
        ("一边手脚", "单侧无力", "说不清话", "说话含糊", "看东西", "视物"),
        ("站立", "行走", "走路", "站不稳"),
        ("便血", "黑便", "黑色大便"),
        ("尿频", "尿急", "尿痛", "排尿"),
        ("皮疹", "红疹", "瘙痒", "红肿"),
    )
    topic_slots = sum(
        1 for terms in clinical_topic_groups if any(term in normalized for term in terms)
    )
    return max(
        normalized.count("？") + normalized.count("?"),
        len(strong_markers) + len(embedded_ma),
        bundled_slots,
        topic_slots,
    )


def final_question_clause(reply: str) -> str:
    """Return only the final actual question, excluding conversational recap text."""
    normalized = compact_text(reply, 900)
    matches = re.findall(r"(?:^|[。！!；;])([^。！!；;]*[？?])", normalized)
    return compact_text(matches[-1], 300) if matches else normalized


def explicit_topic_evidence(transcript: str) -> dict[str, str]:
    """Conservatively mark facts the user stated explicitly to prevent repeat questions."""
    text = compact_text(transcript, 600)
    if not text:
        return {}
    evidence: dict[str, str] = {}
    topic_terms = {
        "breathing": (
            "胸闷", "气短", "呼吸费力", "喘不上气", "喘不过气", "呼吸正常",
            "不胸闷", "不气短", "没有胸闷", "没有气短",
        ),
        "fever": ("发热", "发烧", "发冷", "怕冷", "体温", "没量体温", "没有量体温"),
        "exposure_trigger": (
            "高温", "天气热", "很热", "日晒", "暴晒", "太阳下", "闷热", "剧烈活动",
        ),
        "dehydration": ("喝水", "口干", "尿少", "尿量", "脱水", "补水"),
        "respiratory_features": ("咳嗽", "咳痰", "流鼻涕", "鼻塞", "打喷嚏"),
        "throat_features": ("吞咽", "咽口水", "沙哑", "声音嘶哑", "烧灼感", "干痛"),
        "stool_features": ("便血", "黑便", "黑色大便", "稀便", "水样便"),
        "urinary_features": ("尿频", "尿急", "尿痛", "排尿痛"),
        "skin_features": ("皮疹", "红疹", "瘙痒", "起疙瘩", "水疱"),
        "injury_features": ("出血", "止血", "伤口深", "表皮", "活动正常", "不能活动"),
    }
    for topic, terms in topic_terms.items():
        if any(term in text for term in terms):
            evidence[topic] = text[:180]
    return evidence


def infer_question_topic(question: str) -> str:
    normalized = compact_text(question, 600)
    ordered = (
        "headache_red_flags",
        "headache_onset",
        "onset",
        "fever",
        "breathing",
        "throat_features",
        "respiratory_features",
        "stool_features",
        "dehydration",
        "digestive_features",
        "urinary_features",
        "skin_features",
        "injury_features",
        "exposure_trigger",
        "severity",
        "main_symptom",
        "symptom_detail",
    )
    for topic in ordered:
        if any(term in normalized for term in _TOPIC_TERMS[topic]):
            return topic
    return "symptom_detail" if normalized else ""


def question_matches_topic(question: str, topic: str) -> bool:
    if topic == "symptom_detail":
        return True
    terms = _TOPIC_TERMS.get(topic, ())
    return bool(terms and any(term in question for term in terms))


def topic_is_covered(extracted: InquiryExtractedInformation, topic: str) -> bool:
    return topic in extracted.clarification_answers or topic in extracted.asked_clarifications


def topic_is_resolved(extracted: InquiryExtractedInformation, topic: str) -> bool:
    evidence = compact_text(extracted.clarification_answers.get(topic), 180)
    return bool(evidence and not any(term in evidence for term in _UNKNOWN_EVIDENCE))


def _case_text(extracted: InquiryExtractedInformation) -> str:
    return "；".join(
        value
        for value in (
            extracted.case_summary,
            extracted.symptoms_text,
            "；".join(
                observation.evidence
                for observation in extracted.observations
                if observation.status == "present" and observation.evidence
            ),
        )
        if value
    )


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _topic_priority(extracted: InquiryExtractedInformation) -> tuple[str, ...]:
    text = _case_text(extracted)
    priorities: list[str] = []

    if _has_any(text, ("头痛", "头疼", "太阳穴", "脑袋痛", "脑壳痛")):
        if _has_any(text, ("嗓子", "咽痛", "喉咙", "沙哑")):
            priorities.extend(("throat_features", "fever", "headache_red_flags", "severity"))
        elif _has_any(text, ("咳嗽", "流鼻涕", "鼻塞", "咳痰")):
            priorities.extend(("respiratory_features", "fever", "headache_red_flags", "severity"))
        else:
            priorities.extend(("headache_onset", "headache_red_flags", "fever", "severity"))
    elif _has_any(text, ("嗓子", "咽痛", "喉咙", "沙哑")):
        priorities.extend(("throat_features", "fever", "breathing", "respiratory_features"))
    elif _has_any(text, ("咳嗽", "咳痰", "流鼻涕", "鼻塞", "打喷嚏")):
        priorities.extend(("breathing", "respiratory_features", "fever", "severity"))
    elif _has_any(text, ("中暑", "暴晒", "高温", "闷热", "暑热", "暑湿")):
        priorities.extend(("exposure_trigger", "digestive_features", "dehydration", "fever", "severity"))
    elif _has_any(text, ("腹泻", "拉肚子", "稀便")):
        priorities.extend(("stool_features", "dehydration", "fever", "severity"))
    elif _has_any(text, ("反酸", "烧心")):
        priorities.extend(("digestive_features", "severity", "dehydration", "fever"))
    elif _has_any(text, ("恶心", "呕吐", "胃痛", "腹痛")):
        priorities.extend(("digestive_features", "dehydration", "severity", "fever"))
    elif _has_any(text, ("便秘", "排不出", "没排便")):
        priorities.extend(("digestive_features", "severity", "stool_features"))
    elif _has_any(text, ("尿频", "尿急", "尿痛", "排尿", "小便")):
        priorities.extend(("urinary_features", "fever", "severity"))
    elif _has_any(text, ("皮疹", "红疹", "瘙痒", "皮肤", "红肿")):
        priorities.extend(("skin_features", "breathing", "fever", "severity"))
    elif _has_any(text, ("擦伤", "割伤", "扭伤", "伤口", "出血", "受伤")):
        priorities.extend(("injury_features", "severity"))
    elif _has_any(text, ("头晕", "眩晕", "站不稳", "眼前发黑")):
        priorities.extend(("symptom_detail", "exposure_trigger", "breathing", "severity", "fever"))
    else:
        priorities.extend(("severity", "symptom_detail", "fever"))

    return tuple(dict.fromkeys(priorities))


def select_followup_topic(
    extracted: InquiryExtractedInformation,
    proposed_topic: str = "",
) -> str:
    if not extracted.symptoms_text.strip() and not extracted.case_summary.strip():
        return "main_symptom" if not topic_is_covered(extracted, "main_symptom") else ""
    proposed = normalize_question_topic(proposed_topic)
    pending = normalize_question_topic(extracted.pending_clarification)
    if (
        pending in SYMPTOM_QUESTION_TOPICS
        and pending not in extracted.clarification_answers
        and extracted.asked_clarifications.count(pending) < 2
        and (not proposed or proposed == pending)
    ):
        return pending
    priorities = _topic_priority(extracted)
    if (
        proposed in SYMPTOM_QUESTION_TOPICS
        and not topic_is_covered(extracted, proposed)
    ):
        return proposed
    if not extracted.duration.strip() and not topic_is_covered(extracted, "onset"):
        return "onset"

    for topic in priorities:
        if not topic_is_covered(extracted, topic):
            return topic
    if proposed in SYMPTOM_QUESTION_TOPICS and not topic_is_covered(extracted, proposed):
        return proposed
    return ""


def focused_followup_question(
    extracted: InquiryExtractedInformation,
    proposed_question: str,
    proposed_topic: str,
) -> tuple[str, str]:
    question = compact_text(proposed_question, 300)
    question_clause = final_question_clause(question)
    proposed = normalize_question_topic(
        proposed_topic or infer_question_topic(question_clause)
    )
    volunteered_detail = (
        proposed in _BROAD_DETAIL_TOPICS
        and proposed in extracted.clarification_answers
        and proposed not in extracted.asked_clarifications
        and not _question_repeats_known_detail(
            question_clause,
            extracted.clarification_answers.get(proposed, ""),
        )
    )
    topic = proposed if volunteered_detail else select_followup_topic(extracted, proposed)
    if not topic:
        return "", ""

    invalid = (
        not question_clause
        or independent_question_slot_count(question_clause) != 1
        or topic != proposed
        or not question_matches_topic(question_clause, topic)
        or any(term in question_clause for term in ("另外", "一并告诉", "顺便", "同时还请"))
        or any(term in question_clause for term in ("吃药", "用药", "服药", "药物", "润喉片", "通便药"))
        or any(term in question_clause for term in _ROUTINE_MOBILITY_QUESTION_TERMS)
    )
    if invalid:
        question = _fallback_question(extracted, topic)
    else:
        question = question_clause
    question = plain_language_question(question)
    if "？" not in question and "?" not in question:
        question = f"{question.rstrip('。！!；;')}？"
    return question, topic


def plain_language_question(question: str) -> str:
    """Rewrite a focused question into observable, everyday language."""
    text = compact_text(question, 300)
    text = text.replace(
        "这次头痛有没有伴随异常神经表现，比如单侧无力",
        "头痛时，有没有一边手脚突然使不上力",
    )
    replacements = (
        ("异常神经表现，比如", ""),
        ("神经系统异常，比如", ""),
        ("异常神经表现", "一边手脚突然使不上力"),
        ("神经系统异常", "一边手脚突然使不上力"),
        ("局灶性神经功能缺损", "一边手脚突然使不上力"),
        ("单侧无力", "一边手脚突然使不上力"),
        ("视物异常", "看东西突然模糊或重影"),
        ("言语不清", "突然说不清话"),
        ("说话含糊", "突然说不清话"),
        ("意识障碍", "叫不醒或反应很迟钝"),
        ("颈部僵硬", "脖子硬得低不下头"),
    )
    for professional, everyday in replacements:
        text = text.replace(professional, everyday)
    return re.sub(r"一边手脚突然使不上力(?:，?比如)?一边手脚突然使不上力", "一边手脚突然使不上力", text)


def _fallback_question(extracted: InquiryExtractedInformation, topic: str) -> str:
    text = _case_text(extracted)
    if topic == "digestive_features":
        if _has_any(text, ("中暑", "暴晒", "高温", "闷热", "暑热", "暑湿")):
            return "现在有没有恶心想吐？"
        if _has_any(text, ("反酸", "烧心")):
            return "反酸或烧心时有没有吞咽困难？"
        if _has_any(text, ("便秘", "排不出", "没排便")):
            return "现在有没有明显腹痛？"
    if topic == "symptom_detail" and _has_any(text, ("头晕", "眩晕", "眼前发黑")):
        return "头晕时更像周围在转，还是眼前发黑？"
    return _TOPIC_QUESTIONS[topic]


def _question_repeats_known_detail(question: str, evidence: str) -> bool:
    normalized_question = compact_text(question, 300)
    normalized_evidence = compact_text(evidence, 180)
    if not normalized_question or not normalized_evidence:
        return False
    return any(
        any(term in normalized_question for term in group)
        and any(term in normalized_evidence for term in group)
        for group in _DETAIL_FACT_GROUPS
    )


def minimum_clinical_information_ready(extracted: InquiryExtractedInformation) -> bool:
    if not (extracted.symptoms_text.strip() or extracted.case_summary.strip()):
        return False
    if not extracted.duration.strip():
        return False

    answered = set(extracted.clarification_answers)
    covered = {
        topic
        for topic in answered
        if topic_is_resolved(extracted, topic)
    }
    # An explicit "not measured" answer is sufficient to stop repeating the
    # fever question because the unchanged workflow measures temperature next.
    if "fever" in answered:
        covered.add("fever")
    text = _case_text(extracted)

    if _has_any(text, ("头痛", "头疼", "太阳穴", "脑袋痛", "脑壳痛")):
        if _has_any(text, ("嗓子", "咽痛", "喉咙", "沙哑")):
            return (
                "headache_red_flags" in covered
                and "throat_features" in covered
                and bool(covered & {"fever", "severity"})
            )
        if _has_any(text, ("咳嗽", "流鼻涕", "鼻塞", "咳痰")):
            return (
                "headache_red_flags" in covered
                and "respiratory_features" in covered
                and bool(covered & {"fever", "severity"})
            )
        return (
            "headache_red_flags" in covered
            and bool(covered & {"headache_onset", "fever", "severity"})
        )
    if _has_any(text, ("嗓子", "咽痛", "喉咙", "沙哑")):
        return "throat_features" in covered and bool(covered & {"fever", "breathing"})
    if _has_any(text, ("咳嗽", "咳痰", "流鼻涕", "鼻塞", "打喷嚏")):
        return "respiratory_features" in covered and bool(covered & {"fever", "breathing"})
    if _has_any(text, ("中暑", "暴晒", "高温", "闷热", "暑热", "暑湿")):
        return "exposure_trigger" in covered and bool(covered & {"dehydration", "fever"})
    if _has_any(text, ("腹泻", "拉肚子", "稀便")):
        return {"stool_features", "dehydration"}.issubset(covered)
    if _has_any(text, ("恶心", "呕吐", "胃痛", "腹痛", "反酸", "烧心")):
        return "digestive_features" in covered and bool(covered & {"dehydration", "severity"})
    if _has_any(text, ("便秘", "排不出", "没排便")):
        return "digestive_features" in covered and "severity" in covered
    if _has_any(text, ("尿频", "尿急", "尿痛", "排尿", "小便")):
        return "urinary_features" in covered and "fever" in covered
    if _has_any(text, ("皮疹", "红疹", "瘙痒", "皮肤", "红肿")):
        return "skin_features" in covered and bool(covered & {"breathing", "fever", "severity"})
    if _has_any(text, ("擦伤", "割伤", "扭伤", "伤口", "出血", "受伤")):
        return "injury_features" in covered
    return bool(covered & {"severity", "symptom_detail", "fever", "breathing"})


def medication_question_window(duration: str) -> str:
    value = compact_text(duration, 120)
    if any(term in value for term in ("刚刚", "刚才")):
        return "从刚才这次不舒服开始到现在"
    if any(term in value for term in ("今天早上", "今早", "早上")):
        return "从今天早上这次不舒服开始到现在"
    if any(term in value for term in ("今天中午", "中午")):
        return "从今天中午这次不舒服开始到现在"
    if any(term in value for term in ("今天下午", "下午")):
        return "从今天下午这次不舒服开始到现在"
    if "今天" in value:
        return "从今天这次不舒服开始到现在"
    if any(term in value for term in ("昨晚", "昨天晚上")):
        return "从昨晚这次不舒服开始到现在"
    return "从这次不舒服开始到现在"
