import React, { useState } from "react";
import { askAssistant } from "../api/ai.js";
import { readSpeech } from "../api/audio.js";
import { evaluateInquiry } from "../api/inquiry.js";
import { loadQsmVitals } from "../api/qsm.js";
import { InquiryAssistantCard } from "../components/InquiryAssistantCard.jsx";
import { InquiryForm } from "../components/InquiryForm.jsx";
import { InquiryResultPanel } from "../components/InquiryResultPanel.jsx";

const initialForm = {
  symptoms_text: "",
  duration: "",
  used_medicines: "",
  allergy_or_contraindication: "",
  scene_type: "村镇",
  include_vitals: false
};

export function Inquiry({ notify, onViewCandidates }) {
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [assistantState, setAssistantState] = useState(null);
  const [readingVitals, setReadingVitals] = useState(false);
  const [listening, setListening] = useState(false);

  function handleSubmit(event) {
    event.preventDefault();
    if (!form.symptoms_text.trim()) {
      notify("请先填写症状信息");
      return;
    }

    setSubmitting(true);
    setAssistantState({ loading: true, source: "checking", reply: "正在检查云通道与本地兜底。" });
    evaluateInquiry({
      ...form,
      symptoms_text: form.symptoms_text.trim(),
      duration: form.duration.trim(),
      used_medicines: form.used_medicines.trim(),
      allergy_or_contraindication: form.allergy_or_contraindication.trim()
    })
      .then((data) => {
        setResult(data);
        notify("问询结果已生成");
        const assistantPrompt = [
          `症状：${form.symptoms_text.trim()}`,
          `持续时间：${form.duration.trim() || "未填写"}`,
          `已用药：${form.used_medicines.trim() || "未填写"}`,
          `过敏禁忌：${form.allergy_or_contraindication.trim() || "未填写"}`
        ].join("\n");
        askAssistant(assistantPrompt)
          .then((assistant) => setAssistantState({ ...assistant, loading: false }))
          .catch((error) =>
            setAssistantState({
              ok: false,
              source: "unavailable",
              loading: false,
              reply: error.message || "问询通道暂不可用，已保留 rules 风险分级结果。"
            })
          );
      })
      .catch((error) => {
        setAssistantState(null);
        notify(error.message || "问询失败，请重试");
      })
      .finally(() => setSubmitting(false));
  }

  function handleReadVitals() {
    setReadingVitals(true);
    loadQsmVitals()
      .then((data) => {
        if (data.ok === false) {
          notify(data.error_message || "体征设备暂不可用");
          return;
        }
        const vitalsText = [
          data.temperature != null ? `体温${data.temperature}℃` : "",
          data.heart_rate != null ? `心率${data.heart_rate}` : "",
          data.spo2 != null ? `血氧${data.spo2}%` : ""
        ]
          .filter(Boolean)
          .join("，");
        setForm((current) => ({
          ...current,
          include_vitals: true,
          symptoms_text: current.symptoms_text || vitalsText || "已读取体征，请补充症状"
        }));
        notify(vitalsText ? `体征已读取：${vitalsText}` : "体征读取完成，但部分数据暂不可用");
      })
      .catch((error) => notify(error.message || "体征读取失败"))
      .finally(() => setReadingVitals(false));
  }

  function handleVoiceInput() {
    setListening(true);
    readSpeech(4)
      .then((data) => {
        const text = (data.text || "").trim();
        if (!text) {
          notify("未识别到有效语音，请重试或手动输入");
          return;
        }
        setForm((current) => ({ ...current, symptoms_text: current.symptoms_text ? `${current.symptoms_text}；${text}` : text }));
        notify("语音已识别并填入症状");
      })
      .catch((error) => notify(error.message || "语音识别失败"))
      .finally(() => setListening(false));
  }

  function handleViewCandidates() {
    if (!result?.can_proceed_to_dispense) {
      return;
    }
    const firstMedicine = result.candidate_medicines[0];
    onViewCandidates({
      category: firstMedicine?.category || result.suggested_categories[0] || "全部",
      medicineId: firstMedicine?.id || null
    });
  }

  return (
    <main className="inquiry-page" id="main-content">
      <InquiryForm
        form={form}
        submitting={submitting}
        readingVitals={readingVitals}
        listening={listening}
        onChange={setForm}
        onSubmit={handleSubmit}
        onReadVitals={handleReadVitals}
        onVoiceInput={handleVoiceInput}
      />
      <InquiryAssistantCard result={result} assistantState={assistantState} />
      <InquiryResultPanel result={result} onViewCandidates={handleViewCandidates} />
    </main>
  );
}
