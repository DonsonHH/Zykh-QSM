from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any


@dataclass(frozen=True)
class OfflineSymptomRule:
    key: str
    concept: str
    terms: tuple[str, ...]
    followups: tuple[str, ...]
    medicine_ids: tuple[str, ...]
    alternative_ids: tuple[str, ...] = ()
    needs_vitals: bool = False


RULES = (
    OfflineSymptomRule(
        "heat",
        "暑热不适",
        ("中暑", "暑热", "暴晒", "闷热", "热晕", "头晕恶心", "头晕乏力"),
        ("这种不舒服持续多久了？", "从什么时候开始感觉头晕或不舒服？", "大概不舒服了多长时间？"),
        ("slot-08-huoxiang-zhengqi",),
        needs_vitals=True,
    ),
    OfflineSymptomRule(
        "wound",
        "轻微外伤",
        ("擦伤", "划伤", "刀伤", "破皮", "小伤口", "伤口", "磕破", "外伤"),
        ("伤口现在还能止住血吗？", "现在有没有持续出血或明显肿痛？", "伤口深不深，出血已经止住了吗？"),
        ("slot-17-iodophor", "slot-22-cotton-swab", "slot-20-bandage"),
        ("slot-17-iodophor", "slot-22-cotton-swab", "slot-10-gauze"),
    ),
    OfflineSymptomRule(
        "cold",
        "感冒样不适",
        ("感冒", "流鼻涕", "流涕", "鼻塞", "怕冷", "受凉", "打喷嚏", "发热头痛"),
        ("这些不舒服持续多久了？", "鼻塞、流涕或发冷是从什么时候开始的？", "大概从多久前开始不舒服？"),
        ("slot-03-ganmao-qingre",),
        ("slot-01-fufang-ganmaoling",),
        needs_vitals=True,
    ),
    OfflineSymptomRule(
        "fever",
        "发热头痛不适",
        ("发烧", "发热", "体温高", "头痛", "浑身酸痛", "全身酸痛"),
        ("发热或头痛持续多久了？", "体温升高或头痛是从什么时候开始的？", "大概不舒服了多长时间？"),
        ("slot-01-fufang-ganmaoling",),
        ("slot-03-ganmao-qingre",),
        needs_vitals=True,
    ),
    OfflineSymptomRule(
        "cough",
        "咳嗽咽喉不适",
        ("咳嗽", "咳痰", "喉咙", "咽痛", "嗓子", "声音嘶哑"),
        ("咳嗽或咽喉不适持续多久了？", "现在主要是干咳，还是有痰？", "有没有发热或呼吸费力？"),
        ("slot-05-nin-jiom-pei-pa-koa",),
        ("slot-07-yinhuang", "slot-11-guilin-xiguashuang"),
        needs_vitals=True,
    ),
    OfflineSymptomRule(
        "diarrhea",
        "腹泻肠道不适",
        ("腹泻", "拉肚子", "稀便", "水样便"),
        ("今天大概腹泻了几次？", "腹泻持续多久了，有没有明显口渴乏力？", "从什么时候开始腹泻的？"),
        ("slot-09-bifid-triple",),
        needs_vitals=True,
    ),
    OfflineSymptomRule(
        "mouth",
        "口腔咽喉不适",
        ("口腔溃疡", "口疮", "牙龈肿痛", "咽喉肿痛", "嘴里疼", "口腔疼"),
        ("口腔或咽喉不适持续多久了？", "有没有明显高热或吞咽困难？", "不舒服主要在口腔还是咽喉？"),
        ("slot-11-guilin-xiguashuang",),
        ("slot-07-yinhuang",),
    ),
    OfflineSymptomRule(
        "stomach",
        "胃部不适",
        ("胃痛", "胃酸", "反酸", "烧心", "腹胀", "胃胀", "恶心", "呕吐"),
        ("胃部不适持续多久了？", "是饭前明显，还是饭后更明显？", "有没有持续呕吐或明显腹痛？"),
        ("slot-12-hydrotalcite",),
        ("slot-08-huoxiang-zhengqi",),
        needs_vitals=True,
    ),
    OfflineSymptomRule(
        "constipation",
        "排便困难",
        ("便秘", "排便困难", "大便干", "拉不出来"),
        ("排便困难大概持续几天了？", "最近一次正常排便是什么时候？", "有没有明显腹痛或呕吐？"),
        ("slot-06-lactulose",),
    ),
    OfflineSymptomRule(
        "allergy",
        "鼻部过敏不适",
        ("鼻炎", "鼻痒", "连续打喷嚏", "过敏性鼻炎", "鼻子过敏"),
        ("鼻部不适持续多久了？", "有没有明显喘憋或面唇肿胀？", "这些症状是接触什么之后出现的？"),
        ("slot-18-budesonide-nasal",),
    ),
    OfflineSymptomRule(
        "skin_allergy",
        "皮肤过敏不适",
        ("皮肤过敏", "皮肤瘙痒", "浑身痒", "起疹子", "皮疹", "荨麻疹", "风团"),
        ("皮肤不适持续多久了？", "有没有呼吸费力或面唇肿胀？", "皮疹或瘙痒主要在什么位置？"),
        ("slot-23-desloratadine",),
    ),
    OfflineSymptomRule(
        "fungus",
        "皮肤真菌样不适",
        ("脚气", "真菌", "脱皮", "癣", "趾缝痒"),
        ("皮肤不适持续多久了？", "有没有破溃、渗液或明显红肿？", "不舒服主要在什么位置？"),
        ("slot-16-ketoconazole",),
    ),
    OfflineSymptomRule(
        "pain",
        "肌肉关节不适",
        ("扭伤", "肌肉痛", "关节痛", "膝盖痛", "腰痛", "落枕"),
        ("疼痛持续多久了？", "现在还能正常活动吗？", "有没有明显变形、肿胀或无法负重？"),
        ("slot-19-ketoprofen-gel",),
    ),
    OfflineSymptomRule(
        "eye",
        "眼部干涩",
        ("眼干", "眼涩", "眼睛干", "眼睛涩", "干眼"),
        ("眼部不适持续多久了？", "有没有明显眼痛或视物模糊？", "近期是不是长时间看屏幕？"),
        ("slot-13-sodium-hyaluronate-eye",),
    ),
    OfflineSymptomRule(
        "supplement",
        "营养补充需求",
        ("维生素", "营养补充", "补充营养"),
        ("是日常补充，还是最近有明确不舒服？", "以前是否一直在按说明补充？", "有没有正在使用其他复合维生素？"),
        ("slot-02-centrum",),
    ),
)


GENERIC_DETAIL_QUESTIONS = (
    (
        "不舒服主要在什么位置，最明显的感觉是什么？",
        "请再说说最不舒服的位置和具体感觉。",
    ),
    (
        "现在属于轻微、明显，还是已经影响正常活动？",
        "这种不舒服目前对走路、吃饭或休息有影响吗？",
    ),
    (
        "除了这个表现，还有没有其他同时出现的不舒服？",
        "还伴有发热、疼痛、恶心或其他变化吗？",
    ),
)


SYMPTOM_DETAIL_QUESTIONS = {
    "heat": (
        (
            "除了头晕，有没有恶心、乏力或明显出汗？",
            "现在有没有恶心、没力气或出汗很多？",
            "头晕以外，会不会想吐、浑身没劲或大量出汗？",
        ),
        ("不舒服前有没有暴晒、在闷热环境停留或大量活动？", "出现症状前是不是晒了太阳、待在闷热处或活动较多？"),
        ("休息、通风或补水以后有没有缓解？", "到凉快处休息或喝水以后，感觉有没有好一些？"),
    ),
    "wound": (
        ("伤口在什么位置，大概有多深、多大？", "请说说受伤位置，伤口是浅表擦破还是比较深？"),
        ("伤口现在还在出血吗，有没有异物留在里面？", "出血能止住吗，伤口里有没有看得见的异物？"),
        ("现在有没有明显红肿、疼痛加重或活动受限？", "伤口周围有没有肿、热、明显疼痛或不好活动？"),
    ),
    "cold": (
        ("现在最明显的是鼻塞流涕、怕冷，还是头痛？", "鼻塞、流鼻涕、发冷和头痛里，哪一项最明显？"),
        ("有没有测到发热，或出现明显全身酸痛？", "现在有没有发热、发冷或浑身酸痛？"),
        ("还伴有咳嗽、咽痛或呼吸不舒服吗？", "除了这些，有没有咳嗽、嗓子痛或呼吸费力？"),
    ),
    "fever": (
        ("有没有量过体温，大概是多少？", "目前能确认体温升高吗，测到多少度？"),
        ("有没有发冷、出汗或明显全身酸痛？", "发热时会不会发冷、出很多汗或浑身疼？"),
        ("还伴有咳嗽、呕吐、皮疹或剧烈头痛吗？", "除了发热头痛，还有没有咳嗽、呕吐或其他明显变化？"),
    ),
    "cough": (
        ("现在主要是干咳，还是有痰？", "咳嗽时有没有痰，痰大概是什么样？"),
        ("有没有发热、胸闷或呼吸费力？", "咳嗽时会不会发热、胸口不舒服或喘不上气？"),
        ("嗓子有没有明显疼痛，咳嗽会影响睡觉吗？", "现在嗓子疼不疼，夜里会不会咳得更明显？"),
    ),
    "diarrhea": (
        ("今天大概腹泻了几次？", "从开始到现在大约拉了几次肚子？"),
        ("大便是稀软还是水样，有没有血或黑色表现？", "排便主要是稀便还是水样，有没有异常颜色？"),
        ("有没有明显口渴、乏力、腹痛或呕吐？", "现在会不会很渴、没力气、肚子痛或想吐？"),
    ),
    "stomach": (
        ("不舒服主要在上腹、肚脐周围，还是其他位置？", "胃部不适最明显的位置在哪里？"),
        ("是饭前明显、饭后明显，还是和进食关系不大？", "吃东西前后，哪一个时候更不舒服？"),
        ("有没有持续呕吐、腹泻或疼痛明显加重？", "还伴有呕吐、拉肚子或越来越痛吗？"),
    ),
    "allergy": (
        ("现在最明显的是鼻痒、喷嚏、流涕，还是鼻塞？", "鼻部症状里哪一项最明显？"),
        ("症状是在接触灰尘、花粉或其他东西后出现的吗？", "这次发作前有没有接触可能的过敏原？"),
        ("有没有喘憋、喉咙发紧或面唇肿胀？", "除了鼻部不适，有没有呼吸费力或嘴唇脸部肿胀？"),
    ),
    "skin_allergy": (
        ("皮疹或瘙痒主要在什么位置？", "皮肤不适集中在哪里，范围大不大？"),
        ("是在接触食物、药物或其他东西后出现的吗？", "出现皮疹前有没有吃药、吃特殊食物或接触新物品？"),
        ("有没有呼吸费力、喉咙发紧或面唇肿胀？", "除了皮肤表现，有没有喘憋或脸、嘴唇肿胀？"),
    ),
    "pain": (
        ("疼痛在什么位置，是扭伤、碰撞后出现的吗？", "请说说疼痛位置和出现前发生了什么。"),
        ("现在还能正常活动和负重吗？", "走路、抬手或正常活动会不会明显受影响？"),
        ("有没有明显肿胀、变形、发热或疼痛加重？", "疼痛处有没有肿起来、形状异常或越来越痛？"),
    ),
}


class OfflineInquiryRules:
    """Fast deterministic inquiry path used only when cloud AI is unavailable."""

    EMERGENCY_TERMS = (
        "胸痛", "呼吸困难", "意识不清", "昏迷", "抽搐", "严重过敏",
        "口角歪斜", "单侧无力", "大量出血", "止不住血",
    )
    UNCERTAIN_TERMS = ("不知道", "不清楚", "不确定", "记不清")

    def extract(
        self,
        transcript: str,
        existing: dict[str, Any],
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        text = self._clean(transcript)
        previous_question = self._previous_assistant_question(existing)
        existing_text = "；".join(
            str(existing.get(key) or "")
            for key in ("case_summary", "symptoms_text")
        )
        rule = self._match_rule(f"{text}；{existing_text}")
        turn = max(1, int(existing.get("conversation_turns") or 1))
        detail_question_index = self._detail_question_index(previous_question, rule)

        duration = str(existing.get("duration") or "").strip()
        used = str(existing.get("used_medicines") or "").strip()
        allergy = str(existing.get("allergy_or_contraindication") or "").strip()
        if self._asks_duration(previous_question):
            duration = self._duration(text) or text[:40]
        elif detail_question_index is None:
            duration = self._duration(text) or duration
        if self._asks_used_medicine(previous_question):
            used = self._used_medicine(text)
        elif self._has_explicit_used_medicine(text):
            used = self._used_medicine(text)
        if self._asks_allergy(previous_question):
            allergy = self._allergy(text)
        elif self._has_explicit_allergy(text):
            allergy = self._allergy(text)

        complaint_text = self._complaint(text, rule, previous_question, existing)
        observations = self._existing_observations(existing)
        if detail_question_index is not None:
            detail_concept = (
                rule.concept
                if rule
                else str(existing.get("case_summary") or "身体不适").strip()
            )
            observations = self._upsert_observation(
                observations,
                f"{detail_concept}·补充{detail_question_index + 1}",
                text,
                turn,
                confidence=0.86,
            )
        elif rule and complaint_text and not self._is_context_answer(previous_question):
            observations = self._upsert_observation(
                observations,
                rule.concept,
                complaint_text,
                turn,
            )
        elif not rule and complaint_text and not self._is_context_answer(previous_question):
            observations = self._upsert_observation(
                observations,
                self._short_complaint(complaint_text),
                complaint_text,
                turn,
                confidence=0.7,
            )

        case_summary = rule.concept if rule else str(existing.get("case_summary") or "").strip()
        if not case_summary and complaint_text:
            case_summary = self._short_complaint(complaint_text)
        detail_count = self._detail_answer_count(observations, case_summary)
        downstream_started = self._downstream_started(existing)
        summary_prefix = (
            f"我先整理一下：目前主要是{case_summary}。"
            if detail_count >= 3 and detail_question_index == 2
            else ""
        )
        risk_level, risk_signals = self._risk(text, existing_text)
        vitals = existing.get("vitals") if isinstance(existing.get("vitals"), dict) else {}

        if risk_level == "emergency":
            action = "escalate"
            reply = "你描述的情况可能需要立即处理，请马上联系医生或救援人员。"
            reason = "出现紧急风险关键词"
        elif not case_summary:
            action = "ask"
            reply = self._variant(
                ("请说说现在最明显的不舒服是什么？", "今天哪里最不舒服？请慢慢说。", "先告诉我目前最困扰你的症状。"),
                text,
                turn,
            )
            reason = "等待明确主诉"
        elif not downstream_started and detail_count < 3:
            action = "ask"
            detail_questions = self._detail_questions(rule)
            reply = self._variant(detail_questions[detail_count], text, turn)
            reason = f"补充主要不适信息（{detail_count + 1}/3）"
        elif not duration:
            action = "ask"
            duration_question = self._variant(rule.followups if rule else (
                "这种不舒服持续多久了？", "大概从什么时候开始不舒服？", "现在这个情况有多长时间了？"
            ), text, turn)
            reply = f"{summary_prefix}{duration_question}"
            reason = "补充持续时间"
        elif not used or used == "不确定":
            action = "ask"
            used_question = self._variant((
                "这次不舒服以后有没有用过药？",
                "出现这些不适后，你已经吃过或用过什么药吗？",
                "本次不舒服期间是否已经用药？",
            ), text, turn)
            reply = f"{summary_prefix}{used_question}"
            reason = "补充本次用药"
        elif not allergy or allergy == "不确定":
            action = "ask"
            allergy_question = self._variant((
                "有没有药物过敏，或明确不能使用的药？",
                "接下来确认安全信息：哪些药你过敏或不能用？",
                "请告诉我有没有药物过敏或用药禁忌。",
            ), text, turn)
            reply = f"{summary_prefix}{allergy_question}"
            reason = "补充过敏和禁忌"
        elif rule and rule.needs_vitals and not self._vitals_finished(vitals):
            action = "measure_vitals"
            reply = "这些信息还需要结合额温、心率和血氧，请按页面提示完成一次测量。"
            reason = "核心体征有助于当前安全判断"
        else:
            action = "analyze"
            reply = "信息已经整理完成，接下来核对家庭药品和安全提示。"
            reason = "离线问询信息已齐全"

        return {
            "ok": True,
            "source": "offline_rules",
            "case_summary": case_summary,
            "observations": observations,
            "uncertainties": [],
            "history_relationship": {
                "related": False,
                "similarities": [],
                "important_changes": [],
                "should_reuse_previous_conclusion": False,
            },
            "duration": duration,
            "used_medicines": used,
            "allergy_or_contraindication": allergy,
            "next_action": action,
            "next_question": reply if action == "ask" else "",
            "assistant_reply": reply,
            "reason": reason,
            "risk_level": risk_level,
            "risk_signals": risk_signals,
            "confidence": 0.9 if rule else 0.72,
        }

    def rank(self, context: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        text = self._ranking_text(context)
        rule = self._match_rule(text)
        if not rule:
            return {"ok": True, "source": "offline_rules", "summary": "未匹配到合适的家庭药品。", "options": []}
        available = {str(item.get("id") or ""): item for item in candidates}
        options: list[dict[str, Any]] = []
        primary = [medicine_id for medicine_id in rule.medicine_ids if medicine_id in available][:3]
        alternative = [medicine_id for medicine_id in rule.alternative_ids if medicine_id in available][:3]
        if primary:
            options.append(self._option("primary", "主方案", rule, primary, available))
        if alternative and tuple(alternative) != tuple(primary):
            options.append(self._option("alternative", "备选方案", rule, alternative, available))
        return {
            "ok": True,
            "source": "offline_rules",
            "summary": f"本地问询已按“{rule.concept}”整理可核对的家庭药品。",
            "options": options,
        }

    @staticmethod
    def recommendation(context: dict[str, Any]) -> dict[str, Any]:
        options = [item for item in context.get("options") or [] if isinstance(item, dict)]
        reasons = {
            str(item.get("option_id") or ""): str(item.get("when") or "请结合当前情况核对这一选择。")[:100]
            for item in options
            if item.get("option_id")
        }
        if not reasons:
            return {"ok": False, "source": "assistant"}
        return {
            "ok": True,
            "source": "offline_rules",
            "summary": str(context.get("reasoning_summary") or "本次信息已整理完成。")[:120],
            "option_reasons": reasons,
        }

    @staticmethod
    def _option(
        option_id: str,
        label: str,
        rule: OfflineSymptomRule,
        medicine_ids: list[str],
        available: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if rule.key == "wound":
            reason = "适合用于浅表小伤口的清洁、消毒和覆盖保护。"
        elif rule.key == "heat":
            reason = "当前描述以暑热、头晕或胃肠不适为主，可对照说明书核验。"
        else:
            reason = f"当前描述更接近{rule.concept}，可对照药品说明核验。"
        return {
            "option_id": option_id,
            "label": label,
            "reason": reason,
            "medicine_ids": medicine_ids,
            "usage_by_medicine": {
                medicine_id: str(available[medicine_id].get("dosage") or "")
                for medicine_id in medicine_ids
            },
        }

    @classmethod
    def _match_rule(cls, text: str) -> OfflineSymptomRule | None:
        compact = cls._clean(text)
        # Ranking receives the normalized case summary. Prefer that exact
        # concept over overlapping symptom words such as "咽喉" or "发热".
        for rule in RULES:
            if rule.concept in compact:
                return rule
        for rule in RULES:
            if any(term in compact for term in rule.terms):
                return rule
        return None

    @classmethod
    def _risk(cls, text: str, existing_text: str) -> tuple[str, list[str]]:
        joined = f"{text}；{existing_text}"
        for term in cls.EMERGENCY_TERMS:
            if term in joined and not re.search(rf"(?:没有|没|无|否认){re.escape(term)}", joined):
                return "emergency", [f"用户提到{term}"]
        if any(term in joined for term in ("高热不退", "持续胸闷", "剧烈疼痛", "严重外伤")):
            return "high", ["症状存在持续或严重表现"]
        if any(term in joined for term in ("持续三天", "三天以上", "反复", "头晕", "呕吐")):
            return "medium", ["症状持续或仍需进一步观察"]
        return "low", []

    @staticmethod
    def _existing_observations(existing: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(item) for item in existing.get("observations") or [] if isinstance(item, dict)]

    @staticmethod
    def _detail_questions(rule: OfflineSymptomRule | None) -> tuple[tuple[str, ...], ...]:
        return SYMPTOM_DETAIL_QUESTIONS.get(
            rule.key if rule else "",
            GENERIC_DETAIL_QUESTIONS,
        )

    @classmethod
    def _detail_question_index(
        cls,
        question: str,
        rule: OfflineSymptomRule | None,
    ) -> int | None:
        compact = cls._clean(question)
        if not compact:
            return None
        for index, variants in enumerate(cls._detail_questions(rule)):
            if any(cls._clean(variant) in compact for variant in variants):
                return index
        return None

    @staticmethod
    def _detail_answer_count(observations: list[dict[str, Any]], case_summary: str) -> int:
        prefix = f"{case_summary}·补充"
        indexes = {
            int(match.group(1))
            for item in observations
            if (
                match := re.fullmatch(
                    rf"{re.escape(prefix)}([1-3])",
                    str(item.get("concept") or ""),
                )
            )
        }
        return len(indexes)

    @classmethod
    def _downstream_started(cls, existing: dict[str, Any]) -> bool:
        if str(existing.get("used_medicines") or "").strip():
            return True
        if str(existing.get("allergy_or_contraindication") or "").strip():
            return True
        return any(
            isinstance(message, dict)
            and str(message.get("role") or "") == "assistant"
            and cls._is_context_answer(str(message.get("content") or ""))
            for message in existing.get("conversation") or []
        )

    @staticmethod
    def _upsert_observation(
        observations: list[dict[str, Any]],
        concept: str,
        evidence: str,
        turn: int,
        *,
        confidence: float = 0.92,
    ) -> list[dict[str, Any]]:
        filtered = [item for item in observations if str(item.get("concept") or "") != concept]
        filtered.append({
            "concept": concept[:80],
            "status": "present",
            "evidence": evidence[:180],
            "source_turn": turn,
            "confidence": confidence,
        })
        return filtered[-8:]

    @classmethod
    def _complaint(
        cls,
        text: str,
        rule: OfflineSymptomRule | None,
        previous_question: str,
        existing: dict[str, Any],
    ) -> str:
        if cls._is_context_answer(previous_question):
            return ""
        if cls._is_generic_answer(text):
            return ""
        if rule:
            return text
        if existing.get("case_summary"):
            return ""
        if not text or len(text) < 2 or cls._is_generic_answer(text):
            return ""
        return text

    @staticmethod
    def _short_complaint(text: str) -> str:
        value = re.sub(r"^(?:我感觉|我觉得|我好像|我有点|我有一点|就是)", "", text).strip()
        value = re.split(r"[，。；！？,.!?]", value)[0].strip()
        return value[:18] or "身体不适"

    @staticmethod
    def _duration(text: str) -> str:
        match = re.search(
            r"(?:刚刚|刚才|刚开始|今天|昨天|昨晚|前天|"
            r"(?:半|[零一二两三四五六七八九十百\d]+)(?:分钟?|小时|天|周|个月|月)(?:左右|多)?)",
            text,
        )
        return match.group(0)[:40] if match else ""

    @classmethod
    def _used_medicine(cls, text: str) -> str:
        if cls._negative(text):
            return "未使用"
        if any(term in text for term in cls.UNCERTAIN_TERMS):
            return "不确定"
        return text[:120] if text else "不确定"

    @classmethod
    def _allergy(cls, text: str) -> str:
        if cls._negative(text):
            return "无"
        if any(term in text for term in cls.UNCERTAIN_TERMS):
            return "不确定"
        match = re.search(r"(?:对)?([^，。；、\s]{1,18})(?:过敏|不能吃|不能用|禁忌)", text)
        if match:
            subject = re.sub(r"^(?:我|有|我是|我对)", "", match.group(1)).strip()
            return f"{subject or match.group(1)}过敏或禁忌"
        return text[:120] if text else "不确定"

    @staticmethod
    def _negative(text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        emphatic_negative = re.search(r"(?:^|我说|都|真的|确实|还)(?:没有|没|无)(?:了|啊|呢|呀|的)?", compact)
        return bool(emphatic_negative) or compact in {"无", "没有", "没", "都没有", "这些都没有", "没有的", "不用", "还没有"} or any(
            term in compact for term in ("没有过敏", "无过敏", "没有禁忌", "没用药", "没有用药", "没吃药", "还没用")
        )

    @staticmethod
    def _has_explicit_used_medicine(text: str) -> bool:
        return any(term in text for term in ("吃过药", "用过药", "没吃药", "没用药", "已经吃", "已经用"))

    @staticmethod
    def _has_explicit_allergy(text: str) -> bool:
        return any(term in text for term in ("过敏", "禁忌", "不能吃", "不能用"))

    @staticmethod
    def _previous_assistant_question(existing: dict[str, Any]) -> str:
        for message in reversed(existing.get("conversation") or []):
            if isinstance(message, dict) and str(message.get("role") or "") == "assistant":
                return str(message.get("content") or "")
        return ""

    @staticmethod
    def _asks_duration(question: str) -> bool:
        return any(term in question for term in ("持续", "多久", "多长时间", "什么时候开始"))

    @staticmethod
    def _asks_used_medicine(question: str) -> bool:
        return any(term in question for term in ("用过药", "用药", "吃过", "吃药", "服药"))

    @staticmethod
    def _asks_allergy(question: str) -> bool:
        return any(term in question for term in ("过敏", "禁忌", "不能使用", "不能用"))

    @classmethod
    def _is_context_answer(cls, question: str) -> bool:
        return cls._asks_duration(question) or cls._asks_used_medicine(question) or cls._asks_allergy(question)

    @classmethod
    def _is_generic_answer(cls, text: str) -> bool:
        return cls._negative(text) or text in {"是", "对", "好的", "可以", "不确定", "不知道"}

    @staticmethod
    def _vitals_finished(vitals: dict[str, Any]) -> bool:
        return str(vitals.get("status") or "") in {"complete", "failed", "cancelled", "unavailable"}

    @staticmethod
    def _variant(options: tuple[str, ...], text: str, turn: int) -> str:
        digest = hashlib.sha256(f"{text}|{turn}".encode("utf-8")).digest()
        return options[digest[0] % len(options)]

    @staticmethod
    def _ranking_text(context: dict[str, Any]) -> str:
        observations = "；".join(
            f"{item.get('concept', '')}；{item.get('evidence', '')}"
            for item in context.get("observations") or []
            if isinstance(item, dict)
        )
        return "；".join((str(context.get("case_summary") or ""), observations))

    @staticmethod
    def _clean(value: object) -> str:
        return re.sub(r"\s+", "", str(value or "")).strip("。．.，, ")
