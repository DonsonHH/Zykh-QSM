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
from .local_inquiry_status import local_inquiry_status
from .offline_inquiry_rules import OfflineInquiryRules
from .spoken_answer import is_contextual_negative_answer, is_uncertain_answer
from .weather_context_service import WeatherContextService


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

    def __init__(
        self,
        local_client: LocalAiClient | None = None,
        weather_context: WeatherContextService | None = None,
    ) -> None:
        self.local_client = local_client or LocalAiClient()
        self.weather_context = weather_context or WeatherContextService()
        self.offline_inquiry = OfflineInquiryRules()

    def status(self) -> dict[str, Any]:
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        return {
            "ok": True,
            "mode": settings.ai_mode,
            "cloud_configured": bool(key),
            "cloud_model": settings.ai_model,
            "local": local_inquiry_status(self.local_client.status()),
            "offline_inquiry_ready": self._use_offline_inquiry_rules(),
        }

    def warm_local(self) -> dict[str, Any]:
        if (
            self._use_local_ai_runtime()
            and self._use_offline_inquiry_rules()
        ):
            return {
                "ok": True,
                "ready": True,
                "mode": "offline_rules",
                "message": "本地问询规则已就绪。",
            }
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
        if self._use_local_ai_runtime():
            return self._local_model_reply(message, "当前为离线模式。")
        if not key:
            return self._local_model_reply(message, "未配置云端密钥。")
        if not self._should_attempt_cloud():
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
        if self._use_local_ai_runtime():
            local_reason = "当前为离线模式。"
        elif not key:
            local_reason = "未配置云端密钥。"
        elif not self._should_attempt_cloud():
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
            "你是智药康护的中文多轮AI健康问询语义理解器，不是关键词回复程序。你必须完整理解口语、"
            "同义表达、否定、补充、纠正和同一句中的多个症状，不能只抓住其中一个词继续固定流程。"
            "你负责自然问询、病例理解和语义风险判断，但不能替代医生诊断或处方，不能选择药品、仓位或控制硬件。"
            "只输出一个 JSON 对象。不要套用症状分类白名单；observations.concept 按用户真实表达自由概括。"
            "每条 observation 的 concept 必须使用简短中文，并含 status=present|absent|uncertain、用户原话 evidence、原话所在 source_turn"
            " 和 confidence；没有说过的信息保持未知，否定表达不得写成 present。"
            "完整阅读 conversation、profile、vitals、recent_history 和问询主题记忆；历史只用于比较，不得复用旧结论。"
            "case_state.asked_clarifications 是助手已经实际问过的症状主题，case_state.clarification_answers 是已得到的回答证据，"
            "case_state.pending_clarification 是上一问的主题。正常回答过或已经问过的主题不得重复追问。"
            "answered_topics_this_turn 只记录最新用户原话真正回答的主题；即使用户回答‘无、还没有、不知道’也要正确记录，"
            "topic_evidence 用简短原话保存证据。用户明确纠正主诉时 material_symptom_change=true，并以纠正后的症状重新评估。"
            "symptom_change_type 只能是 none、add、refine、replace：新增同时存在的症状是 add，进一步描述同一症状是 refine，"
            "明确说明原症状说错、不是原症状而是另一症状才是 replace；replace 时必须列出 replaced_concepts。"
            "symptom_scope_complete 表示用户已经明确回答过‘是否还有其他同时出现的不适’，或用户原话已经说明‘就这些、别的没有’。"
            "本字段由服务端用于先完整收集症状范围，不要把它误当成病名判断。"
            "每轮最多提出一个可独立回答的信息槽，只能有一个问号；不能把起病时间、发热、严重程度、已用药、过敏和病史塞进一句。"
            "面向普通家庭和老人提问，必须使用能直接感受到的生活化说法；不要说‘异常神经表现、神经系统异常、"
            "局灶性神经功能缺损、视物异常、意识障碍’等分类术语。一次只问一种具体表现，例如说‘一边手脚突然使不上力’。"
            "普通轻症不得追问能否站立、能否正常行走或走路是否受影响；用户主动提到站不稳时只把它作为已有风险信息。"
            "如果用户同时说嗓子疼和头痛，必须同时保留两项；下一问选择最能改变风险或后续处理的一项，不能忽略另一项。"
            "question_topic 必须从 main_symptom、onset、fever、breathing、headache_onset、headache_red_flags、severity、"
            "respiratory_features、throat_features、digestive_features、stool_features、dehydration、urinary_features、"
            "skin_features、injury_features、exposure_trigger、symptom_detail、none 中选择。"
            "case_state.symptom_followups_remaining 表示当前有效主诉周期还可提出几个真正的症状澄清问题，当前周期上限四个；"
            "用户明确 replace 后服务端会开启新周期。为 0 时不得再问症状。"
            "选择下一问前，先比较两到四个与全部现有症状相符的常见原因方向和必须排除的风险方向，"
            "只问最能区分这些方向、改变风险等级或改变后续处理的一个问题；不要按固定字段顺序机械追问。"
            "症状信息足够时 clinical_ready=true 并选择 analyze，不要为了凑满四次继续追问；仍不足时只问一个最高价值缺口。"
            "已用药、过敏禁忌、体征测量和药品筛选由后续本地业务链单独完成，本轮不要提前询问或给药。"
            "next_action 只能是 ask、measure_vitals、analyze、escalate、end。先形成明确主诉；"
            "出现明显危险信号时选择 escalate。risk_level 只能是 low、medium、high、emergency。"
            "只有用户明确表示不再继续、要求结束本次问询时才选择 end。"
            "assistant_reply 是直接给用户的一句自然回应；ask 时只包含一个聚焦问题；"
            "analyze、escalate 或 end 时 next_question 和 question_topic 必须为空或 none。"
            "最终必须返回 output_contract 所示的完整根对象，不能只返回一条 observation；"
            "observations 必须逐项覆盖 current_utterance 中每个明确出现或明确否定的症状，不得只保留第一个症状。"
            "history_relationship.should_reuse_previous_conclusion 必须为 false。"
        )
        user_payload = {
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
                "answered_topics_this_turn": [],
                "topic_evidence": {},
                "question_topic": "none",
                "clinical_ready": False,
                "material_symptom_change": False,
                "symptom_change_type": "none",
                "replaced_concepts": [],
                "symptom_scope_complete": False,
                "next_action": "ask",
                "next_question": "",
                "assistant_reply": "",
                "reason": "",
                "risk_level": "low",
                "risk_signals": [],
                "confidence": 0.0,
            },
        }
        if self._use_local_ai_runtime():
            return self._offline_inquiry_extract(transcript, existing, profile, "当前为离线模式。")
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key:
            return self._offline_inquiry_extract(transcript, existing, profile, "未配置云端密钥。")
        if not self._should_attempt_cloud():
            return self._offline_inquiry_extract(transcript, existing, profile, "云端网络不可用。")
        environment_context = self.weather_context.inquiry_context(transcript, existing)
        if environment_context:
            user_payload["environment_context"] = environment_context
            system_prompt += (
                f" 当前服务地点预设为{settings.inquiry_location_name}。environment_context 是实时环境背景，"
                "只可辅助决定追问方向，不能仅凭天气认定中暑或其他病因，也不能替代本次体征。"
            )
        user_prompt = json.dumps(user_payload, ensure_ascii=False)

        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.15,
            "max_tokens": 1600,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        self._apply_provider_options(
            payload,
            enable_thinking=settings.ai_inquiry_enable_thinking,
            reasoning_effort="low",
        )
        parsed, cloud_error = self._request_json_completion(
            payload,
            key,
            purpose="inquiry_extract",
        )
        if isinstance(parsed, dict) and not self._valid_inquiry_extract_payload(parsed):
            repair_payload = dict(payload)
            repair_payload["messages"] = [
                *payload["messages"],
                {
                    "role": "assistant",
                    "content": json.dumps(parsed, ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": (
                        "上一个响应不是完整且类型严格的问诊状态根对象。请重新读取最初的 current_utterance，"
                        "严格按 output_contract 返回完整 JSON。必须包含 case_summary、observations 数组、"
                        "next_action、assistant_reply、risk_level；clinical_ready、material_symptom_change 和"
                        "symptom_scope_complete 必须是真正的 JSON 布尔值，不能使用字符串。"
                        "同一句中的每个明确症状都要分别保留。不要解释，不要只返回单条 observation。"
                    ),
                },
            ]
            repaired, repair_error = self._request_json_completion(
                repair_payload,
                key,
                purpose="inquiry_extract_contract_repair",
            )
            if self._valid_inquiry_extract_payload(repaired):
                parsed = repaired
                cloud_error = ""
            else:
                parsed = None
                cloud_error = repair_error or "云端返回的问诊结构不完整"
        if not isinstance(parsed, dict):
            fallback = self._offline_inquiry_extract(
                transcript,
                existing,
                profile,
                f"云端问询失败：{cloud_error or '未返回有效结构'}。",
            )
            fallback["fallback_reason"] = cloud_error or "云端未返回有效结构"
            return fallback
        return {"ok": True, "source": "cloud", **parsed}

    def rank_inquiry_candidates(
        self,
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Let AI rank only IDs already admitted by the deterministic safety pool."""
        system_prompt = (
            "你是家庭康护问询的临床信息分析与候选药品排序助手。程序已完成库存、有效期、OTC资格和初步过敏过滤。"
            "你只能从 candidates 中选择，不能新增药品、改变字段或控制药柜。"
            "你仍必须逐项核对 candidates 的 contraindications、tags、dosage 和 safety_note，"
            "结合已用药、慢病史、过敏史和体征排除禁忌、同类重复及不合理组合；无法确认安全时不要选择。"
            "结合病例、个人信息、体征和药品说明决定是否存在合适候选；不合适可返回空 options。"
            "即使 candidates 为空，也必须完成 assessment，并把 options 返回为空数组。"
            "低风险或中风险情况下，只要候选中存在与当前情况直接相关且安全的外用药、保健品或护理用品，"
            "就应输出至少一个主方案，不应仅因不需要口服药或处方药而返回空 options。"
            "浅表擦伤、已经止血的轻微刀伤等场景，可把碘伏、棉签、纱布、创口贴等外伤护理用品"
            "按实际清洁、消毒、覆盖顺序组成一个方案；不要为了凑方案加入无关口服药。"
            "只有所有候选均与当前情况无关，或病例需要先由专业人员处理时，才返回空 options。"
            "最多输出一个主方案和一个备选方案，两个方案均必须完整、可单独选择，备选不是联合服用。"
            "如果候选中存在用途侧重不同、同样符合当前情况的第二种安全选择，应输出备选方案；"
            "只有确实没有合理第二选择时才只给主方案，不要把同一护理流程强行拆成两个方案。"
            "每个方案最多四个药品，只有确需按顺序完成的护理组合才可包含多个药品。"
            "assessment 必须结合全部主诉、伴随症状、起病经过、体征、病史和已用药生成，不得只围绕第一个症状。"
            "possible_conditions 最多三项，name 写常见的可能病因或可能疾病名称，likelihood 只能是 more_likely、possible、"
            "needs_exclusion；只能表达可能性，不得下确定诊断。supporting_evidence_ids 和 non_supporting_evidence_ids"
            "只能引用 case.evidence_catalog 中真实存在的 ID，不得自造事实。每项各最多两个 ID。"
            "assessment.summary 用不超过三句话解释为什么形成这些可能性；next_steps 和 seek_care_if 各最多三条，简短可执行。"
            "不要在模型输出中写免责声明，终端会固定显示安全声明。"
            "reason 用一至两句结合本人的实际症状、体征或病史说明为什么此方案更合适，"
            "不使用‘覆盖症状、库存核验、独立备选、互斥’等程序语言。"
            "不得声称已经诊断，不得使用‘一定有效、保证有效、可以治好’等疗效承诺。"
            "reason_by_medicine 和 usage_by_medicine 必须逐项使用 medicine_id 作为键。reason_by_medicine 要说明该药"
            "针对本人的哪项实际症状或为何作为配合项，不能只抄主治说明；usage_by_medicine 写简短、可播报的使用顺序和用法。"
            "外用护理用品可以写‘先、再、最后’的操作顺序；口服或局部药品只能在候选 dosage 的剂量、"
            "频次、疗程和适用年龄范围内取值，不得增加剂量、频次或疗程，不确定时原样使用 dosage。"
            "只输出 JSON：{\"assessment\":{\"summary\":\"\",\"possible_conditions\":[{\"name\":\"\","
            "\"likelihood\":\"possible\",\"supporting_evidence_ids\":[\"obs-1\"],"
            "\"non_supporting_evidence_ids\":[\"vital-temperature\"]}],\"next_steps\":[\"\"],"
            "\"seek_care_if\":[\"\"]},\"options\":[{\"option_id\":\"primary\",\"label\":\"主方案\","
            "\"reason\":\"\",\"medicine_ids\":[\"\"],\"reason_by_medicine\":{\"medicine-id\":\"个性化理由\"},"
            "\"usage_by_medicine\":{\"medicine-id\":\"本次建议用法\"}}]}。"
        )
        user_prompt = json.dumps(
            {"case": context, "candidates": candidates},
            ensure_ascii=False,
        )
        if self._use_local_ai_runtime():
            return self._offline_inquiry_rank(system_prompt, user_prompt, context, candidates, "")
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key or not self._should_attempt_cloud():
            return self._offline_inquiry_rank(
                system_prompt, user_prompt, context, candidates, "云端排序不可用。"
            )
        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "instructions": system_prompt,
            "input": user_prompt,
            "reasoning": {"effort": "low"},
            "text": {"format": {"type": "json_object"}},
            "max_output_tokens": 8192,
        }
        parsed, cloud_error = self._request_json_response(
            payload,
            key,
            purpose="inquiry_rank",
        )
        if isinstance(parsed, dict):
            return {"ok": True, "source": "cloud_responses", **parsed}

        # The handoff target is Responses, but some DeepSeek deployments only
        # publish the OpenAI-compatible Chat Completions contract. Keep the
        # final assessment online when that documented endpoint is available.
        chat_payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        self._apply_provider_options(
            chat_payload,
            enable_thinking=settings.ai_enable_thinking,
            reasoning_effort="high",
        )
        chat_parsed, chat_error = self._request_json_completion(
            chat_payload,
            key,
            purpose="inquiry_rank_chat_fallback",
        )
        if isinstance(chat_parsed, dict):
            return {"ok": True, "source": "cloud_chat_fallback", **chat_parsed}
        return self._offline_inquiry_rank(
            system_prompt,
            user_prompt,
            context,
            candidates,
            (
                "云端排序失败："
                f"{cloud_error or 'Responses 未返回有效结构'}；"
                f"{chat_error or 'Chat Completions 未返回有效结构'}。"
            ),
        )

    @staticmethod
    def _use_offline_inquiry_rules() -> bool:
        # Tests and explicit legacy deployments can still exercise the old
        # small-model adapter by setting OFFLINE_INQUIRY_MODE=model.
        return str(getattr(settings, "offline_inquiry_mode", "model")).lower() == "rules"

    def _offline_inquiry_extract(
        self,
        transcript: str,
        existing: dict[str, Any],
        profile: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        if self._use_offline_inquiry_rules():
            return self.offline_inquiry.extract(transcript, existing, profile)
        return self._extract_inquiry_local(transcript, existing, profile, reason)

    def _offline_inquiry_rank(
        self,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
        reason: str,
    ) -> dict[str, Any]:
        if self._use_offline_inquiry_rules():
            return self.offline_inquiry.rank(context, candidates)
        return self._rank_inquiry_candidates_local(system_prompt, user_prompt, reason)

    def _offline_recommendation(
        self,
        system_prompt: str,
        user_prompt: str,
        option_ids: list[str],
        context: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        if self._use_offline_inquiry_rules():
            return self.offline_inquiry.recommendation(context)
        return self._generate_recommendation_local(system_prompt, user_prompt, option_ids, reason)

    def _rank_inquiry_candidates_local(
        self,
        _system_prompt: str,
        user_prompt: str,
        _reason: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(user_prompt)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "source": "ai_unavailable",
                "message": "离线模型排序输入无效。",
            }
        context = payload.get("case") if isinstance(payload.get("case"), dict) else {}
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        if not context or not candidates:
            return {"ok": True, "source": "local_llm", "summary": "", "options": []}

        compact_case = {
            "s": str(context.get("case_summary") or "")[:80],
            "f": [
                {
                    "c": str(item.get("concept") or "")[:28],
                    "v": str(item.get("status") or "present")[:10],
                    "e": str(item.get("evidence") or "")[:48],
                }
                for item in context.get("observations") or []
                if isinstance(item, dict)
            ][:4],
            "d": str(context.get("duration") or "")[:32],
            "m": str(context.get("used_medicines") or "")[:36],
            "a": str(context.get("allergy_or_contraindication") or "")[:44],
            "r": str(context.get("risk_level") or "")[:12],
            "v": context.get("vitals") or {},
        }
        focused = self._semantic_focus_candidates(compact_case, candidates)
        if focused is not None:
            candidates = focused
        if len(candidates) > 6:
            narrowed = self._local_candidate_category_pool(compact_case, candidates)
            if narrowed is None:
                return {
                    "ok": False,
                    "source": "ai_unavailable",
                    "message": "离线模型暂未完成候选类别理解。",
                }
            if not narrowed:
                return {"ok": True, "source": "local_llm", "summary": "", "options": []}
            candidates = narrowed
        catalog: dict[str, list[list[str]]] = {}
        for candidate in candidates:
            if not str(candidate.get("id") or "").strip():
                continue
            category = str(candidate.get("category") or "其他")[:12]
            catalog.setdefault(category, []).append(
                [
                    str(candidate.get("name") or "")[:16],
                    str(candidate.get("indications") or "")[:42],
                ]
            )
        compact_catalog = [[category, items] for category, items in catalog.items()]
        system_prompt = (
            "你是家庭康护问询的候选理解助手。安全程序已过滤库存、有效期、OTC和绝对禁忌。"
            "只从候选中选择与case直接相关的用品；不相关就返回空，不要因一个相似字硬选。"
            "最多两个方案，每个最多四个药品；备选不是同时使用。浅表伤口可按清洁、消毒、覆盖顺序组合。"
            "只输出一行：主方案写A=后接catalog中的药品名称，再写逗号和简短原因；"
            "有备选时继续写分号和B=。名称必须原样复制。没有合适候选只输出NONE。不要输出剂量。"
        )
        compact_prompt = json.dumps(
            # Catalog first maximizes llama.cpp prompt-cache reuse across
            # inquiry sessions; only the trailing case changes per user.
            {"catalog": compact_catalog, "case": compact_case},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        result = self.local_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": compact_prompt},
            ],
            temperature=0.0,
            max_tokens=32,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "source": "ai_unavailable",
                "message": "离线模型暂未完成候选排序。",
            }
        reply = str(result.get("reply") or "")
        line_options = self._parse_local_rank_line(reply, candidates)
        if line_options is not None:
            return {
                "ok": True,
                "source": "local_llm",
                "summary": "",
                "options": line_options,
            }
        parsed = self._parse_json_content(reply)
        if not isinstance(parsed, dict):
            # A small local model can hit its output limit after the closing
            # array but before the outer JSON brace. Recover the complete
            # scalar fields and key array without inventing any field.
            option_match = re.search(
                r"\{\s*\"label\"\s*:\s*\"(?P<label>[^\"]*)\".*?"
                r"\"reason\"\s*:\s*\"(?P<reason>[^\"]*)\".*?"
                r"\"medicine_(?:keys|ids)\"\s*:\s*\[(?P<keys>[^\]]*)\]",
                reply,
                flags=re.DOTALL,
            )
            if option_match:
                parsed = {
                    "options": [
                        {
                            "label": option_match.group("label"),
                            "reason": option_match.group("reason"),
                            "medicine_keys": re.findall(
                                r'"([^"\r\n]+)"', option_match.group("keys")
                            ),
                        }
                    ]
                }
            else:
                parsed = None
        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "source": "ai_unavailable",
                "message": "离线模型未返回可解析的候选排序。",
            }
        if "options" not in parsed and any(
            key in parsed for key in ("medicine_ids", "medicine_keys", "ids", "i")
        ):
            parsed = {"options": [parsed]}
        raw_options = parsed.get("options")
        if not isinstance(raw_options, list):
            raw_options = parsed.get("o") if isinstance(parsed.get("o"), list) else []
        allowed_ids = {str(item.get("id") or "").strip() for item in candidates}
        key_to_id: dict[str, str] = {}
        for item in candidates:
            medicine_id = str(item.get("id") or "").strip()
            slot = str(item.get("slot") or "").strip()
            if not medicine_id:
                continue
            key_to_id[medicine_id] = medicine_id
            if slot:
                key_to_id[slot] = medicine_id
                key_to_id[f"slot-{slot}"] = medicine_id
        options: list[dict[str, Any]] = []
        for raw in raw_options[:2]:
            if not isinstance(raw, dict):
                continue
            raw_ids = raw.get("medicine_ids")
            if not isinstance(raw_ids, list):
                raw_ids = raw.get("medicine_keys")
            if not isinstance(raw_ids, list):
                raw_ids = raw.get("ids") if isinstance(raw.get("ids"), list) else raw.get("i")
            if not isinstance(raw_ids, list):
                continue
            medicine_ids = list(
                dict.fromkeys(
                    key_to_id.get(str(value or "").strip(), "")
                    for value in raw_ids[:4]
                    if key_to_id.get(str(value or "").strip(), "") in allowed_ids
                )
            )
            if not medicine_ids:
                continue
            usage = raw.get("usage_by_medicine")
            usage = usage if isinstance(usage, dict) else raw.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            options.append(
                {
                    "option_id": "primary" if not options else "alternative",
                    "label": str(raw.get("label") or ("主方案" if not options else "备选方案")),
                    "reason": str(raw.get("reason") or raw.get("r") or "").strip(),
                    "medicine_ids": medicine_ids,
                    "usage_by_medicine": usage,
                }
            )
        return {
            "ok": True,
            "source": "local_llm",
            "summary": str(parsed.get("summary") or parsed.get("s") or "").strip()[:120],
            "options": options,
        }

    def _local_candidate_category_pool(
        self,
        compact_case: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        categories = list(
            dict.fromkeys(
                str(candidate.get("category") or "").strip()
                for candidate in candidates
                if str(candidate.get("category") or "").strip()
            )
        )
        if not categories:
            return None
        category_evidence: dict[str, list[str]] = {}
        for candidate in candidates:
            category = str(candidate.get("category") or "").strip()
            if not category:
                continue
            description = "；".join(
                value
                for value in (
                    str(candidate.get("name") or "").strip(),
                    str(candidate.get("indications") or "").strip(),
                    str(candidate.get("safety_note") or "").strip(),
                )
                if value
            )[:180]
            if description:
                category_evidence.setdefault(category, []).append(description)
        result = self.local_client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "根据case和每个类别下的药品适用描述，选择最多两个直接相关类别。"
                        "必须优先依据适用描述，不要只看类别名称；例如暑湿/中暑应优先看含‘暑湿’或‘化湿’描述的类别，"
                        "不能因为都带‘感冒’二字就把风寒感冒药当成暑湿不适的首选。"
                        "只回复类别名，用逗号分隔；无明确不适或无相关类别只回复NONE。不要解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "case": compact_case,
                            "categories": categories,
                            "category_evidence": category_evidence,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=16,
        )
        if not result.get("ok"):
            return None
        reply = str(result.get("reply") or "").strip()
        if re.match(r"^(?:NONE|无|没有合适)", reply, flags=re.IGNORECASE):
            return []
        selected = [category for category in categories if category in reply][:2]
        if not selected:
            return None
        return [
            candidate
            for candidate in candidates
            if str(candidate.get("category") or "").strip() in selected
        ]

    @staticmethod
    def _semantic_focus_candidates(
        compact_case: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Remove obvious semantic mismatches before the small model ranks options.

        This is deliberately a narrow contradiction guard, not a medicine selector.
        The model still chooses the final option and wording from the focused pool.
        """
        case_text = "；".join(
            str(value or "")
            for value in (
                compact_case.get("s"),
                "；".join(
                    str(item.get("e") or "")
                    for item in compact_case.get("f") or []
                    if isinstance(item, dict)
                ),
            )
        )
        focus_groups = (
            (
                ("中暑", "暑湿", "暴晒", "晒了", "高温天气"),
                ("暑湿", "化湿", "暑湿感冒", "藿香正气"),
            ),
        )
        for triggers, matches in focus_groups:
            if not any(trigger in case_text for trigger in triggers):
                continue
            scored: list[tuple[int, dict[str, Any]]] = []
            for candidate in candidates:
                medicine_text = "；".join(
                    str(candidate.get(field) or "")
                    for field in ("name", "category", "indications", "safety_note")
                )
                score = sum(1 for term in matches if term in medicine_text)
                scored.append((score, candidate))
            best = max((score for score, _candidate in scored), default=0)
            focused = [candidate for score, candidate in scored if score == best and score > 0]
            if best >= 2 and focused and len(focused) < len(candidates):
                return focused
        return None

    @staticmethod
    def _parse_local_rank_line(
        reply: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        text = re.sub(r"\s+", " ", str(reply or "")).strip()
        if not text:
            return None
        if re.match(r"^(?:NONE|无|没有合适)", text, flags=re.IGNORECASE):
            return []
        key_to_id: dict[str, str] = {}
        name_to_id: dict[str, str] = {}
        for item in candidates:
            medicine_id = str(item.get("id") or "").strip()
            slot = str(item.get("slot") or "").strip()
            if medicine_id and slot:
                key_to_id[slot] = medicine_id
            name = str(item.get("name") or "").strip()
            if medicine_id and name:
                name_to_id[name] = medicine_id
        options: list[dict[str, Any]] = []
        matches = list(
            re.finditer(
                r"(?:^|[;；])\s*([AB])\s*=\s*(.*?)(?=(?:[;；]\s*[AB]\s*=)|$)",
                text,
                flags=re.IGNORECASE,
            )
        )
        for match in matches:
            segment = match.group(2).strip()
            names = [name for name in name_to_id if name in segment][:4]
            medicine_ids = [name_to_id[name] for name in names]
            if not medicine_ids:
                numeric_prefix = re.match(
                    r"([0-9]+(?:\s*[,，]\s*[0-9]+){0,3})",
                    segment,
                )
                keys = (
                    re.split(r"\s*[,，]\s*", numeric_prefix.group(1))
                    if numeric_prefix
                    else []
                )
                medicine_ids = [key_to_id[key] for key in keys if key in key_to_id]
            medicine_ids = list(
                dict.fromkeys(medicine_ids)
            )
            if not medicine_ids:
                continue
            option_name = match.group(1).upper()
            reason = segment
            for name in names:
                reason = reason.replace(name, "")
            reason = re.sub(r"^[\s,，|｜:：-]+", "", reason).strip()
            options.append(
                {
                    "option_id": "primary" if option_name == "A" else "alternative",
                    "label": "主方案" if option_name == "A" else "备选方案",
                    "reason": reason[:40],
                    "medicine_ids": medicine_ids,
                    "usage_by_medicine": {},
                }
            )
        return options[:2] if options else None

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
        if self._use_local_ai_runtime():
            return self._offline_recommendation(system_prompt, user_prompt, option_ids, context, "")
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key or not self._should_attempt_cloud():
            return self._offline_recommendation(
                system_prompt, user_prompt, option_ids, context, "云端当前不可用。"
            )

        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.35,
            "max_tokens": 220,
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
            return self._offline_recommendation(
                system_prompt,
                user_prompt,
                option_ids,
                context,
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
            max_tokens=180,
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
        if self._use_local_ai_runtime():
            return {"ok": False, "source": "assistant"}
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if not key or not self._should_attempt_cloud():
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
        answer_target = self._pending_answer_target(existing)
        if self._is_contextual_answer(transcript, answer_target):
            expanded = {
                "case_summary": str(existing.get("case_summary") or "").strip(),
                "observations": [],
                "uncertainties": [],
                "history_relationship": {},
                "duration": str(existing.get("duration") or "").strip(),
                "used_medicines": str(existing.get("used_medicines") or "").strip(),
                "allergy_or_contraindication": str(existing.get("allergy_or_contraindication") or "").strip(),
                "next_question": "",
                "assistant_reply": "",
                "reason": "",
                "next_action": "ask",
                "risk_level": "low",
                "risk_signals": [],
                "confidence": 0.0,
            }
            self._apply_contextual_answer(expanded, transcript, answer_target, existing)
            self._complete_local_inquiry(expanded, existing)
            return {"ok": True, "source": "local_llm", **expanded}
        compact_existing = {
            "t": int(existing.get("conversation_turns") or 0),
            "s": str(existing.get("case_summary") or "")[:80],
            "f": [
                {
                    "c": str(item.get("concept") or "")[:40],
                    "s": str(item.get("status") or "")[:10],
                    "e": str(item.get("evidence") or "")[:40],
                    "t": int(item.get("source_turn") or 0),
                }
                for item in existing.get("observations") or []
                if isinstance(item, dict)
            ][:6],
            "u": list(existing.get("uncertainties") or [])[:3],
            "du": str(existing.get("duration") or "")[:40],
            "m": str(existing.get("used_medicines") or "")[:60],
            "a": str(existing.get("allergy_or_contraindication") or "")[:60],
            "v": existing.get("vitals") or {},
            "h": [
                {
                    "title": str(item.get("title") or "")[:40],
                    "summary": str(
                        item.get("reasoning_summary")
                        or item.get("reply")
                        or item.get("case_summary")
                        or ""
                    )[:80],
                }
                for item in existing.get("recent_history") or []
                if isinstance(item, dict)
            ][:1],
            "c": [
                {
                    "r": str(message.get("role") or "")[:1],
                    "x": str(message.get("content") or "")[:36],
                }
                for message in (existing.get("conversation") or [])[-6:]
                if isinstance(message, dict)
            ],
            "target": answer_target,
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
            # 72 tokens is often enough for Chinese prose but can cut the JSON
            # closing brace off on this small model. Keep the response compact,
            # while leaving enough room for one observation and one question.
            max_tokens=96,
            response_format={"type": "json_object"},
        )
        if not result.get("ok"):
            return self._local_continuity_result(transcript, existing, reason)
        raw_reply = str(result.get("reply") or "")
        parsed = self._parse_json_content(raw_reply)
        if not isinstance(parsed, dict) or not any(
            key in parsed
            for key in (
                "summary",
                "s",
                "facts",
                "f",
                "duration",
                "du",
                "used_medicines",
                "m",
                "allergy",
                "a",
                "action",
                "n",
            )
        ):
            recovered = self._recover_local_inquiry_prefix(raw_reply)
            parsed = recovered if isinstance(recovered, dict) else parsed
        if not isinstance(parsed, dict):
            recovered = self._recover_local_transcript(transcript, existing)
            if recovered:
                self._complete_local_inquiry(recovered, existing)
                return {"ok": True, "source": "local_llm", **recovered}
            return self._local_continuity_result(transcript, existing, reason)
        expanded = self._expand_local_inquiry(
            parsed,
            transcript=transcript,
            source_turn=max(1, int(existing.get("conversation_turns") or 1)),
            suppress_observations=self._is_contextual_answer(transcript, answer_target),
        )
        self._apply_contextual_answer(expanded, transcript, answer_target, existing)
        has_extracted_context = any(
            str(expanded.get(field) or "").strip()
            for field in (
                "case_summary",
                "duration",
                "used_medicines",
                "allergy_or_contraindication",
            )
        )
        if not expanded.get("observations") and not has_extracted_context:
            recovered = self._recover_local_transcript(transcript, existing)
            if recovered:
                self._complete_local_inquiry(recovered, existing)
                return {"ok": True, "source": "local_llm", **recovered}
            return self._local_continuity_result(transcript, existing, "离线模型未提取到明确病例信息。")
        self._complete_local_inquiry(expanded, existing)
        return {"ok": True, "source": "local_llm", **expanded}

    @classmethod
    def _local_inquiry_system_prompt(cls) -> str:
        return (
            "你是问询信息整理器，只凭said和known理解口语。不得诊断、选药或控硬件。"
            "仅输出一行JSON：summary、facts、action、question、duration、"
            "used_medicines、allergy；可含change_type、replaced_concepts、scope_complete。"
            "facts最多2项，含concept、status、evidence；status仅present、absent、uncertain；"
            "action仅ask、measure_vitals、analyze、escalate、end。summary和concept必须来自said；"
            "同句多症状分别保留，否定项只能absent，未知留空，不得补造事实或病因。"
            "纠正旧主诉用change_type=replace并列旧症状；新增或细化用add、refine，否则none。"
            "scope_complete仅在用户已回答有无其他不适时为true。"
            "question只问一件事、不重复known；说人话，不问能否站立或行走。"
            "无不适则facts=[]并问哪里不舒服；主诉明确且体征有帮助才measure_vitals。"
        )

    @classmethod
    def _expand_local_inquiry(
        cls,
        payload: dict[str, Any],
        *,
        transcript: str = "",
        source_turn: int = 1,
        suppress_observations: bool = False,
    ) -> dict[str, Any]:
        if "observations" in payload:
            if suppress_observations:
                return {**payload, "observations": []}
            return payload
        observations: list[dict[str, Any]] = []
        raw_facts = [] if suppress_observations else (
            payload.get("f")
            if isinstance(payload.get("f"), list)
            else payload.get("facts") if isinstance(payload.get("facts"), list) else []
        )
        for item in raw_facts:
            if isinstance(item, dict):
                concept = str(item.get("concept") or item.get("c") or "").strip()
                status = str(item.get("status") or item.get("s") or "uncertain").strip()
                evidence = str(item.get("evidence") or item.get("e") or "").strip()
                item_source_turn = item.get("source_turn") or item.get("t") or source_turn
                confidence = item.get("confidence") or item.get("p") or 0
            elif isinstance(item, list) and item:
                concept = str(item[0] or "").strip()
                status = str(item[1] if len(item) > 1 else "uncertain").strip()
                evidence = str(item[2] if len(item) > 2 else "").strip()
                item_source_turn = item[3] if len(item) > 3 else source_turn
                confidence = item[4] if len(item) > 4 else 0
            else:
                continue
            if not concept:
                continue
            if evidence in {"用户原话", "原话", "said"}:
                evidence = cls._compact_text(transcript, 100)
            else:
                evidence = re.sub(r"^(?:said|用户原话)\s*[:：]\s*", "", evidence).strip()
            if status == "absent" and not cls._contains_negation(evidence):
                status = "present"
            observations.append(
                {
                    "concept": concept,
                    "status": status,
                    "evidence": evidence,
                    "source_turn": item_source_turn,
                    "confidence": confidence,
                }
            )
        if not observations and not suppress_observations:
            raw_dimensions = payload.get("d") if isinstance(payload.get("d"), list) else []
            for value in raw_dimensions[:3]:
                concept = cls._compact_text(value, 28)
                if concept and concept not in {"主诉词", "症状", "不适"}:
                    observations.append(
                        {
                            "concept": concept,
                            "status": "present",
                            "evidence": cls._compact_text(transcript, 100),
                            "source_turn": source_turn,
                            "confidence": payload.get("c") or 0.7,
                        }
                    )
        raw_intents = [] if suppress_observations else (
            payload.get("p") if isinstance(payload.get("p"), list) else []
        )
        for value in raw_intents[:2]:
            concept = cls._compact_text(value, 28)
            if not concept or concept in {item.get("concept") for item in observations}:
                continue
            observations.append(
                {
                    "concept": concept,
                    "status": "present",
                    "evidence": cls._compact_text(transcript, 100),
                    "source_turn": source_turn,
                    "confidence": payload.get("c") or 0.65,
                }
            )
        return {
            "case_summary": str(
                payload.get("s")
                or payload.get("summary")
                or payload.get("case_summary")
                or ""
            ).strip(),
            "observations": observations,
            "uncertainties": payload.get("u") if isinstance(payload.get("u"), list) else [],
            "history_relationship": payload.get("h") if isinstance(payload.get("h"), dict) else {},
            "duration": str(payload.get("du") or payload.get("duration") or "").strip(),
            "used_medicines": str(
                payload.get("m")
                or payload.get("used_medicines")
                or payload.get("medicines")
                or payload.get("medications_taken")
                or ""
            ).strip(),
            "allergy_or_contraindication": str(
                payload.get("a")
                or payload.get("allergy")
                or payload.get("allergy_or_contraindication")
                or payload.get("allergies")
                or ""
            ).strip(),
            "next_question": str(
                payload.get("q") or payload.get("next_question") or payload.get("question") or ""
            ).strip(),
            "assistant_reply": str(
                payload.get("r")
                or payload.get("assistant_reply")
                or payload.get("q")
                or payload.get("next_question")
                or payload.get("question")
                or ""
            ).strip(),
            "reason": str(payload.get("x") or "").strip(),
            "next_action": str(
                payload.get("n")
                or payload.get("action")
                or payload.get("next_action")
                or "ask"
            ).strip(),
            "risk_level": str(payload.get("k") or payload.get("risk_level") or "low").strip(),
            "risk_signals": (
                payload.get("g")
                if isinstance(payload.get("g"), list)
                else payload.get("risk_flags") if isinstance(payload.get("risk_flags"), list) else []
            ),
            "symptom_change_type": str(
                payload.get("change_type") or payload.get("symptom_change_type") or "none"
            ).strip(),
            "replaced_concepts": (
                payload.get("replaced_concepts")
                if isinstance(payload.get("replaced_concepts"), list)
                else []
            ),
            "symptom_scope_complete": type(
                payload.get("scope_complete")
                if "scope_complete" in payload
                else payload.get("symptom_scope_complete")
            ) is bool
            and bool(
                payload.get("scope_complete")
                if "scope_complete" in payload
                else payload.get("symptom_scope_complete")
            ),
            "confidence": payload.get("c") or payload.get("confidence") or 0,
        }

    @classmethod
    def _complete_local_inquiry(
        cls,
        expanded: dict[str, Any],
        existing: dict[str, Any],
    ) -> None:
        if not str(expanded.get("case_summary") or "").strip():
            expanded["case_summary"] = str(existing.get("case_summary") or "").strip()
        if str(expanded.get("case_summary") or "").strip() in {
            "20字内摘要",
            "病例摘要",
            "摘要",
        }:
            observations = expanded.get("observations") or []
            expanded["case_summary"] = "、".join(
                str(item.get("concept") or "").strip()
                for item in observations
                if isinstance(item, dict) and str(item.get("concept") or "").strip()
            )[:60]
        if not str(expanded.get("case_summary") or "").strip():
            expanded["case_summary"] = "、".join(
                str(item.get("concept") or "").strip()
                for item in expanded.get("observations") or []
                if isinstance(item, dict) and str(item.get("concept") or "").strip()
            )[:60]
        for target, source in (
            ("duration", "duration"),
            ("used_medicines", "used_medicines"),
            ("allergy_or_contraindication", "allergy_or_contraindication"),
        ):
            if not str(expanded.get(target) or "").strip():
                expanded[target] = str(existing.get(source) or "").strip()

        action = str(expanded.get("next_action") or "ask").strip()
        question = str(expanded.get("next_question") or "").strip()
        reply = str(expanded.get("assistant_reply") or question).strip()
        observations = [
            item
            for item in expanded.get("observations") or []
            if isinstance(item, dict) and str(item.get("concept") or "").strip()
        ]
        if action == "ask" and (observations or expanded.get("case_summary")):
            if cls._generic_opening_question(reply) and not cls._generic_opening_question(question):
                reply = question
            if cls._generic_opening_question(question or reply):
                question = ""
                reply = ""
        if action == "ask" and not cls._looks_like_question(question or reply):
            question = ""
            reply = ""
        if action == "ask" and cls._question_repeats_known_complaint(question, expanded):
            question = ""
            reply = ""
        if action == "ask" and not reply:
            if not expanded.get("duration"):
                reply = "这种不舒服大概持续多久了？"
            elif not expanded.get("used_medicines"):
                reply = "这次不舒服以后有没有用过药？"
            elif not expanded.get("allergy_or_contraindication"):
                reply = "有没有药物过敏或明确不能使用的药？"
            else:
                action = "analyze"
        expanded["next_action"] = action
        expanded["assistant_reply"] = reply
        expanded["next_question"] = (question or reply) if action == "ask" else question

    @staticmethod
    def _generic_opening_question(value: str) -> bool:
        compact = re.sub(r"\s+", "", value or "")
        return any(
            phrase in compact
            for phrase in (
                "哪里不舒服",
                "哪儿不舒服",
                "什么地方不舒服",
                "说说哪里不舒服",
                "今天有什么不舒服",
                "现在感觉如何",
                "目前感觉如何",
            )
        )

    @staticmethod
    def _looks_like_question(value: str) -> bool:
        compact = re.sub(r"\s+", "", value or "")
        if not compact:
            return False
        return compact.endswith(("？", "?")) or any(
            term in compact
            for term in (
                "多久",
                "多长时间",
                "有没有",
                "是否",
                "哪里",
                "哪儿",
                "什么",
                "如何",
                "怎么",
                "吗",
                "呢",
            )
        )

    @classmethod
    def _pending_answer_target(cls, existing: dict[str, Any]) -> dict[str, str]:
        conversation = existing.get("conversation") or []
        for message in reversed(conversation):
            if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
                continue
            question = re.sub(r"\s+", "", str(message.get("content") or ""))
            if any(term in question for term in ("过敏", "禁忌", "不能使用", "不能用")):
                return {"field": "allergy_or_contraindication", "question": question[:80]}
            if any(term in question for term in ("用过药", "用药", "吃过药", "吃药", "服药")):
                return {"field": "used_medicines", "question": question[:80]}
            if any(term in question for term in ("持续", "多久", "多长时间")):
                return {"field": "duration", "question": question[:80]}
            if cls._generic_opening_question(question):
                return {"field": "chief_complaint", "question": question[:80]}
            return {"field": "clinical_follow_up", "question": question[:80]}
        return {"field": "", "question": ""}

    @staticmethod
    def _is_contextual_answer(transcript: str, target: dict[str, str]) -> bool:
        field = target.get("field")
        if field == "duration":
            return bool(AiService._duration_context_value(transcript))
        compact = re.sub(r"[\s，。！？,.!?]", "", transcript or "")
        if field == "clinical_follow_up":
            return is_contextual_negative_answer(transcript)
        if field not in {"used_medicines", "allergy_or_contraindication"}:
            return False
        if is_contextual_negative_answer(transcript) or is_uncertain_answer(transcript):
            return True
        if field == "used_medicines":
            return any(
                term in compact
                for term in ("没吃药", "没有吃药", "没用药", "没有用药", "还没用药", "还没有用药", "未使用药物", "用过药", "吃过药", "已用药")
            )
        return compact in {
            "有",
            "有过敏",
            "有禁忌",
            "有不能用的药",
        } or any(
            term in compact
            for term in (
                "没有过敏",
                "无过敏",
                "没有禁忌",
                "无禁忌",
                "对药物过敏",
                "药物过敏",
                "不能用",
            )
        )

    @classmethod
    def _apply_contextual_answer(
        cls,
        expanded: dict[str, Any],
        transcript: str,
        target: dict[str, str],
        existing: dict[str, Any],
    ) -> None:
        if not cls._is_contextual_answer(transcript, target):
            return
        expanded["observations"] = []
        expanded["case_summary"] = str(existing.get("case_summary") or "").strip()
        compact = re.sub(r"[\s，。！？,.!?]", "", transcript or "")
        uncertain = is_uncertain_answer(transcript)
        if target.get("field") == "used_medicines":
            if uncertain:
                expanded["used_medicines"] = "不确定"
            elif any(term in compact for term in ("用过药", "吃过药", "已用药")):
                expanded["used_medicines"] = transcript[:120]
            else:
                expanded["used_medicines"] = "未使用"
        elif target.get("field") == "allergy_or_contraindication":
            negative = is_contextual_negative_answer(transcript) or any(
                term in compact
                for term in (
                    "没有药物过敏",
                    "无药物过敏",
                    "没有过敏",
                    "无过敏",
                    "没有禁忌",
                    "无禁忌",
                    "没有不能用的药",
                    "没有不能使用的药",
                )
            )
            generic_affirmative = compact in {
                "有",
                "有过敏",
                "有禁忌",
                "有不能用的药",
                "对药物过敏",
                "药物过敏",
            }
            if uncertain:
                expanded["allergy_or_contraindication"] = "不确定"
            elif negative:
                expanded["allergy_or_contraindication"] = "无"
            elif generic_affirmative:
                expanded["allergy_or_contraindication"] = ""
                expanded["next_action"] = "ask"
                expanded["assistant_reply"] = "具体是哪一种药物过敏或不能使用？"
                expanded["next_question"] = expanded["assistant_reply"]
            else:
                expanded["allergy_or_contraindication"] = transcript[:120]
        elif target.get("field") == "duration":
            expanded["duration"] = cls._duration_context_value(transcript)
        elif target.get("field") == "clinical_follow_up":
            concept = cls._follow_up_concept(target.get("question") or "")
            if concept:
                expanded["observations"] = [
                    {
                        "concept": concept,
                        "status": "absent",
                        "evidence": cls._compact_text(transcript, 100),
                        "source_turn": 0,
                        "confidence": 1.0,
                    }
                ]

    @staticmethod
    def _duration_context_value(transcript: str) -> str:
        match = re.search(
            r"(?:刚刚|刚才|刚开始|没多久|今天|昨晚|昨天|前天|"
            r"(?:大约|大概|差不多)?(?:半|[零一二两三四五六七八九十百\d]+)"
            r"(?:分钟?|小时|钟头|天|周|星期|个月|月|年)(?:半|左右|上下|多)?)",
            transcript or "",
        )
        if not match:
            return ""
        value = match.group(0)
        for prefix in ("大约", "大概", "差不多"):
            value = value.removeprefix(prefix)
        return value

    @classmethod
    def _follow_up_concept(cls, question: str) -> str:
        value = re.sub(r"[\s？?。！!]", "", question or "")
        value = re.sub(r"^(?:请问)?(?:您|你)?(?:现在|目前)?", "", value)
        value = re.sub(r"^(?:有没有|有无|是否|会不会|是不是)(?:出现|伴有|伴随)?", "", value)
        value = re.sub(r"(?:吗|呢)$", "", value)
        return cls._compact_text(value, 28)

    @staticmethod
    def _contains_negation(value: str) -> bool:
        return bool(re.search(r"(?:没有|无|未见|不伴|并无|不是|否认|没|未)\s*", value or ""))

    @staticmethod
    def _question_repeats_known_complaint(
        question: str,
        expanded: dict[str, Any],
    ) -> bool:
        if not question:
            return False
        for observation in expanded.get("observations") or []:
            if not isinstance(observation, dict):
                continue
            concept = str(observation.get("concept") or "").strip()
            evidence = str(observation.get("evidence") or "").strip()
            if len(concept) >= 2 and concept in question and concept in evidence:
                return True
        return False

    @classmethod
    def _local_continuity_result(
        cls,
        transcript: str,
        existing: dict[str, Any],
        diagnostic_reason: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "source": "assistant",
            "message": "刚才没有听清或整理出明确的不适，请换一种说法再说一次。",
            "diagnostic_note": diagnostic_reason,
        }

    @classmethod
    def _recover_local_transcript(
        cls,
        transcript: str,
        existing: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Keep a clear utterance when the local model misses its JSON contract.

        This is a lossless transport fallback, not a clinical classifier: it only
        trims speech fillers and stores the user's own words as evidence. It does
        not infer a diagnosis, risk level, medicine, or hardware action.
        """
        raw = cls._compact_text(transcript, 120)
        compact = re.sub(r"[，。！？,.!?；;]", "", raw).strip()
        if not compact or compact in {
            "嗯", "哦", "啊", "好", "好的", "是", "是的", "没有", "无", "不知道", "不清楚",
        }:
            return None

        complaint = re.sub(r"^(?:我说|就是说)", "", compact).strip()
        complaint = re.sub(
            r"^(?:我)?(?:好像|感觉|觉得|似乎|有点|有些|一点|一些|最近|现在|目前)",
            "",
            complaint,
        ).strip()
        complaint = re.sub(r"^(?:有点|有些|一点|一些)", "", complaint).strip()
        complaint = re.sub(r"^我", "", complaint).strip()
        complaint = re.sub(r"(?:了|啦|的)$", "", complaint).strip()
        if len(complaint) < 2:
            return None

        complaint_signals = (
            "中暑", "暑湿", "头晕", "发热", "高热", "咳嗽", "流涕", "鼻塞", "头痛",
            "腹泻", "胃痛", "恶心", "呕吐", "过敏", "瘙痒", "擦伤", "刀伤", "伤口",
            "出血", "胸闷", "心慌", "气短", "喉咙", "嗓子", "疼", "痛", "发冷", "乏力",
            "出汗", "不舒服", "难受", "不适",
        )
        if not any(term in complaint for term in complaint_signals):
            return None

        existing_summary = str(existing.get("case_summary") or "").strip()
        summary = complaint[:40] or existing_summary[:40]
        if not summary:
            return None
        return {
            "case_summary": summary,
            "observations": [
                {
                    "concept": summary,
                    "status": "present",
                    "evidence": raw,
                    "source_turn": max(1, int(existing.get("conversation_turns") or 1)),
                    "confidence": 0.55,
                }
            ],
            "uncertainties": [],
            "history_relationship": {},
            "duration": str(existing.get("duration") or "").strip(),
            "used_medicines": str(existing.get("used_medicines") or "").strip(),
            "allergy_or_contraindication": str(
                existing.get("allergy_or_contraindication") or ""
            ).strip(),
            "next_question": "",
            "assistant_reply": "",
            "reason": "保留用户原话，等待本地模型下一轮继续整理。",
            "next_action": "ask",
            "risk_level": "low",
            "risk_signals": [],
            "confidence": 0.55,
        }

    def generate_medicine_guidance(self, medicine: dict[str, Any]) -> dict[str, Any]:
        """Generate structured reference text without presenting it as verified prescribing data."""
        key = self._read_key(settings.ai_api_key, settings.ai_api_key_file)
        if self._use_local_ai_runtime():
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
        reply = (
            "刚才这句话没有整理完整，请换一种说法再说一次。"
            "如果出现胸痛、呼吸困难或意识异常，请立即联系医生或救援人员。"
        )
        return {
            "ok": True,
            "source": "assistant",
            "model": "local-continuity",
            "reply": reply,
            "offline": True,
            "diagnostic_note": note,
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
            return "请继续说明头晕更像周围在转还是眼前发黑；"
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

    def _should_attempt_cloud(self) -> bool:
        if settings.ai_mode != "auto":
            return True
        return self._cloud_reachable()

    def _use_local_ai_runtime(self) -> bool:
        return settings.ai_mode == "local"

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
    def _valid_inquiry_extract_payload(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        if not (
            isinstance(payload.get("case_summary"), str)
            and isinstance(payload.get("observations"), list)
            and isinstance(payload.get("next_action"), str)
            and isinstance(payload.get("assistant_reply"), str)
            and isinstance(payload.get("risk_level"), str)
        ):
            return False
        return all(
            field not in payload or type(payload[field]) is bool
            for field in (
                "clinical_ready",
                "material_symptom_change",
                "symptom_scope_complete",
            )
        )

    @staticmethod
    def _apply_provider_options(
        payload: dict[str, Any],
        enable_thinking: bool,
        reasoning_effort: str = "high",
    ) -> None:
        api_base = settings.ai_api_base.lower()
        if "deepseek.com" in api_base:
            payload["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
            if enable_thinking:
                payload["reasoning_effort"] = (
                    reasoning_effort
                    if reasoning_effort in {"low", "high", "max"}
                    else "high"
                )
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

    def _request_json_response(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        purpose: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """Call the Responses endpoint for the final inquiry assessment."""
        max_attempts = max(1, min(int(settings.ai_inquiry_max_attempts), 2))
        attempt_timeout = max(
            8.0,
            min(
                float(settings.ai_inquiry_timeout_seconds),
                max(float(settings.ai_inquiry_attempt_timeout_seconds), 30.0),
            ),
        )
        retry_delay = max(0.0, min(float(settings.ai_inquiry_retry_delay_seconds), 2.0))
        endpoint = str(settings.ai_responses_api_base).strip()
        errors: list[str] = []
        retryable_http_codes = {408, 409, 425, 429, 500, 502, 503, 504}

        for attempt in range(1, max_attempts + 1):
            request = Request(
                endpoint,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json",
                    "User-Agent": "ZykhInquiryResponses/1.0",
                },
            )
            retryable = True
            try:
                with urlopen(request, timeout=attempt_timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                status = str(data.get("status") or "completed")
                if status != "completed":
                    incomplete = data.get("incomplete_details")
                    detail = (
                        str(incomplete.get("reason") or "").strip()
                        if isinstance(incomplete, dict)
                        else ""
                    )
                    errors.append(
                        f"Responses 状态 {status}"
                        + (f"（{detail}）" if detail else "")
                    )
                else:
                    parsed = self._parse_json_content(
                        self._extract_responses_output_text(data)
                    )
                    if isinstance(parsed, dict):
                        return parsed, ""
                    errors.append("Responses 返回结构无法解析")
            except HTTPError as exc:
                retryable = exc.code in retryable_http_codes
                errors.append(f"HTTP {exc.code}")
            except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
                errors.append(self._compact_error(exc))

            if not retryable or attempt >= max_attempts:
                break
            if retry_delay:
                time.sleep(retry_delay * attempt)

        error = "；".join(dict.fromkeys(errors)) or "未知错误"
        logger.warning("AI Responses completion failed purpose=%s error=%s", purpose, error)
        return None, error

    @staticmethod
    def _extract_responses_output_text(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    parts.append(str(content.get("text") or ""))
        return "".join(parts).strip()

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
    def _recover_local_inquiry_prefix(content: str) -> dict[str, Any] | None:
        """Recover complete fields when the small model stops before the outer brace."""
        text = (content or "").strip()
        if not text:
            return None
        decoder = json.JSONDecoder()

        def value_after(key: str) -> Any:
            match = re.search(rf'"{re.escape(key)}"\s*:\s*', text)
            if not match:
                return None
            try:
                value, _end = decoder.raw_decode(text[match.end() :])
            except json.JSONDecodeError:
                return None
            return value

        recovered: dict[str, Any] = {}
        for key in (
            "summary",
            "facts",
            "action",
            "question",
            "duration",
            "used_medicines",
            "allergy",
        ):
            value = value_after(key)
            if value is not None:
                recovered[key] = value
        facts = recovered.get("facts")
        return recovered if isinstance(facts, list) and facts else None

    @staticmethod
    def _compact_error(exc: BaseException) -> str:
        detail = re.sub(r"\s+", " ", str(exc or "")).strip()
        if isinstance(exc, TimeoutError) or "timed out" in detail.lower():
            return "读取超时"
        if isinstance(exc, json.JSONDecodeError):
            return "响应不是有效 JSON"
        return detail[:120] or exc.__class__.__name__
