import React, { useRef, useState } from "react";
import { evaluateInquiry } from "../api/inquiry.js";
import { loadQsmVitals } from "../api/qsm.js";
import { InquiryAnalyzingStep } from "../components/InquiryAnalyzingStep.jsx";
import { InquiryFollowupStep } from "../components/InquiryFollowupStep.jsx";
import { InquiryResultStep } from "../components/InquiryResultStep.jsx";
import { InquiryStartStep } from "../components/InquiryStartStep.jsx";
import { SafetyNotice } from "../components/SafetyNotice.jsx";

const initialForm = {
  symptoms_text: "",
  duration: "",
  used_medicines: "",
  allergy_or_contraindication: "",
  scene_type: "村镇",
  include_vitals: false
};

export function Inquiry({ notify, onViewCandidates, onNavigate }) {
  const [step, setStep] = useState("start");
  const [form, setForm] = useState(initialForm);
  const [allergyChoice, setAllergyChoice] = useState("");
  const [result, setResult] = useState(null);
  const [readingVitals, setReadingVitals] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState("");
  const [vitalsMessage, setVitalsMessage] = useState("");
  const [blockedReason, setBlockedReason] = useState("");
  const recognitionRef = useRef(null);

  function updateSymptoms(value) {
    setForm((current) => ({ ...current, symptoms_text: value }));
  }

  function handleQuickSymptom(symptom) {
    setForm((current) => ({ ...current, symptoms_text: symptom }));
  }

  function handleNext() {
    if (!form.symptoms_text.trim()) {
      notify("请先说出或输入症状");
      return;
    }
    setStep("followup");
  }

  function handleVoiceInput() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      const message = "当前语音输入不可用，请手动输入。";
      setVoiceMessage(message);
      notify(message);
      return;
    }

    if (recognitionRef.current) {
      recognitionRef.current.abort();
      recognitionRef.current = null;
    }

    const recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognitionRef.current = recognition;
    setListening(true);
    setVoiceMessage("正在听取症状，请清晰说出哪里不舒服。");

    recognition.onresult = (event) => {
      const text = Array.from(event.results)
        .map((resultItem) => resultItem[0]?.transcript || "")
        .join("")
        .trim();
      if (!text) {
        setVoiceMessage("未识别到有效语音，请手动输入。");
        return;
      }
      setForm((current) => ({
        ...current,
        symptoms_text: current.symptoms_text ? `${current.symptoms_text}；${text}` : text
      }));
      setVoiceMessage("语音已填入症状文本。");
    };

    recognition.onerror = () => {
      const message = "当前语音输入不可用，请手动输入。";
      setVoiceMessage(message);
      notify(message);
    };

    recognition.onend = () => {
      setListening(false);
      recognitionRef.current = null;
    };

    recognition.start();
  }

  function handleReadVitals() {
    setReadingVitals(true);
    setVitalsMessage("正在读取体征……");
    loadQsmVitals()
      .then((data) => {
        if (data.ok === false) {
          const message = "体征设备暂不可用，可继续问询。";
          setVitalsMessage(message);
          notify(message);
          return;
        }
        const vitalsText = [
          data.temperature != null ? `体温${data.temperature}℃` : "",
          data.heart_rate != null ? `心率${data.heart_rate}` : "",
          data.spo2 != null ? `血氧${data.spo2}%` : ""
        ]
          .filter(Boolean)
          .join("，");
        setForm((current) => ({ ...current, include_vitals: true }));
        setVitalsMessage(vitalsText || "体征读取完成，部分数据暂不可用。");
        notify(vitalsText ? `体征已读取：${vitalsText}` : "体征读取完成，部分数据暂不可用");
      })
      .catch(() => {
        const message = "体征设备暂不可用，可继续问询。";
        setVitalsMessage(message);
        notify(message);
      })
      .finally(() => setReadingVitals(false));
  }

  function handleAnalyze() {
    if (!form.duration) {
      notify("请选择持续时间");
      return;
    }
    if (!form.used_medicines) {
      notify("请选择已用药情况");
      return;
    }
    if (!allergyChoice) {
      notify("请选择过敏或禁忌情况");
      return;
    }
    if (allergyChoice === "有" && !form.allergy_or_contraindication.trim()) {
      notify("请输入过敏或禁忌信息");
      return;
    }

    const uncertainty =
      allergyChoice === "不确定" ? "过敏或禁忌信息不确定，暂不进入取药确认。" : "";
    setBlockedReason(uncertainty);
    setStep("analyzing");

    window.setTimeout(() => {
      evaluateInquiry({
        ...form,
        symptoms_text: form.symptoms_text.trim(),
        duration: form.duration,
        used_medicines: form.used_medicines === "未使用" ? "" : form.used_medicines,
        allergy_or_contraindication:
          allergyChoice === "无" ? "" : form.allergy_or_contraindication.trim() || allergyChoice
      })
        .then((data) => {
          setResult(data);
          setStep("result");
        })
        .catch((error) => {
          notify(error.message || "问询失败，请重试");
          setStep("followup");
        });
    }, 520);
  }

  function handleViewCandidates() {
    if (!result?.can_proceed_to_dispense || blockedReason) {
      return;
    }
    const firstMedicine = result.candidate_medicines[0];
    onViewCandidates({
      category: firstMedicine?.category || result.suggested_categories[0] || "全部",
      medicineId: firstMedicine?.id || null
    });
  }

  function resetFlow() {
    setStep("start");
    setForm(initialForm);
    setAllergyChoice("");
    setResult(null);
    setVoiceMessage("");
    setVitalsMessage("");
    setBlockedReason("");
  }

  return (
    <main className="inquiry-page" id="main-content">
      <section className="inquiry-flow-card" aria-label="AI 应急问询流程">
        {step === "start" ? (
          <InquiryStartStep
            symptomsText={form.symptoms_text}
            listening={listening}
            voiceMessage={voiceMessage}
            onSymptomsChange={updateSymptoms}
            onQuickSymptom={handleQuickSymptom}
            onVoiceInput={handleVoiceInput}
            onNext={handleNext}
          />
        ) : step === "followup" ? (
          <InquiryFollowupStep
            form={form}
            allergyChoice={allergyChoice}
            readingVitals={readingVitals}
            vitalsMessage={vitalsMessage}
            onFormChange={setForm}
            onAllergyChoice={setAllergyChoice}
            onReadVitals={handleReadVitals}
            onBack={() => setStep("start")}
            onAnalyze={handleAnalyze}
          />
        ) : step === "analyzing" ? (
          <InquiryAnalyzingStep />
        ) : result ? (
          <InquiryResultStep
            result={result}
            blockedReason={blockedReason}
            onViewCandidates={handleViewCandidates}
            onRestart={resetFlow}
            onHome={() => onNavigate("home")}
          />
        ) : null}
      </section>

      <aside className="inquiry-side-note" aria-label="安全提示">
        <strong>安全边界</strong>
        <SafetyNotice>本系统仅提供风险提示、药品信息匹配和禁忌核验，不能替代专业人员判断。</SafetyNotice>
        <div>
          <span>流程</span>
          <p>先描述症状，再补充持续时间、已用药、过敏禁忌和体征信息。</p>
        </div>
        <div>
          <span>取药</span>
          <p>只有低风险、无明显禁忌且库存可用时，才会进入候选药品查看。</p>
        </div>
      </aside>
    </main>
  );
}
