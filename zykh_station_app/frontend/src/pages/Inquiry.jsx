import React, { useEffect, useRef, useState } from "react";
import { evaluateInquiry } from "../api/inquiry.js";
import { InquiryAnalyzingStep } from "../components/InquiryAnalyzingStep.jsx";
import { InquiryChatStep } from "../components/InquiryChatStep.jsx";
import { InquiryFollowupStep } from "../components/InquiryFollowupStep.jsx";
import { InquiryResultStep } from "../components/InquiryResultStep.jsx";
import { InquiryStartStep } from "../components/InquiryStartStep.jsx";

const initialForm = {
  symptoms_text: "",
  duration: "",
  used_medicines: "",
  allergy_or_contraindication: "",
  scene_type: "家庭",
  include_vitals: false
};

const draftKey = "zykh-inquiry-draft";

function readDraft() {
  try {
    const raw = window.sessionStorage.getItem(draftKey);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function Inquiry({ notify, onViewCandidates, onNavigate }) {
  const initialDraft = readDraft();
  const urlMode = new URLSearchParams(window.location.search).get("inquiryMode") === "chat" ? "chat" : "";
  const [step, setStep] = useState(initialDraft?.step || "start");
  const [form, setForm] = useState(initialDraft?.form || initialForm);
  const [allergyChoice, setAllergyChoice] = useState(initialDraft?.allergyChoice || "");
  const [followupStage, setFollowupStage] = useState(initialDraft?.followupStage || "duration");
  const [result, setResult] = useState(null);
  const [flowMode, setFlowMode] = useState(urlMode || initialDraft?.flowMode || "guided");
  const [listening, setListening] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState("");
  const [vitalsMessage, setVitalsMessage] = useState(initialDraft?.vitalsMessage || "");
  const [blockedReason, setBlockedReason] = useState("");
  const recognitionRef = useRef(null);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(draftKey, JSON.stringify({ step, form, allergyChoice, followupStage, vitalsMessage, flowMode }));
    } catch {
      // sessionStorage is optional; losing a draft must not block inquiry.
    }
  }, [step, form, allergyChoice, followupStage, vitalsMessage, flowMode]);

  function handleQuickSymptom(symptom) {
    setForm((current) => ({ ...current, symptoms_text: symptom }));
  }

  function handleNext() {
    if (!form.symptoms_text.trim()) {
      notify("请先说出症状或点击症状按钮");
      return;
    }
    setFollowupStage("duration");
    setStep("followup");
  }

  function handleVoiceInput() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      const message = "当前语音输入不可用，可点击下方症状按钮。";
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
        setVoiceMessage("未识别到有效语音，可点击症状按钮。");
        return;
      }
      setForm((current) => ({
        ...current,
        symptoms_text: current.symptoms_text ? `${current.symptoms_text}；${text}` : text
      }));
      setVoiceMessage("语音已填入症状文本。");
    };

    recognition.onerror = () => {
      const message = "当前语音输入不可用，可点击下方症状按钮。";
      setVoiceMessage(message);
      notify(message);
    };

    recognition.onend = () => {
      setListening(false);
      recognitionRef.current = null;
    };

    recognition.start();
  }

  function handleOpenVitals() {
    const nextForm = { ...form, include_vitals: true };
    setForm(nextForm);
    setFollowupStage("review");
    setVitalsMessage("请按测量页引导读取体征，完成后返回问询继续。");
    try {
      window.sessionStorage.setItem(
        draftKey,
        JSON.stringify({
          step: "followup",
          form: nextForm,
          allergyChoice,
          followupStage: "review",
          vitalsMessage: "请按测量页引导读取体征，完成后返回问询继续。"
        })
      );
    } catch {
      // sessionStorage is optional; navigation can continue without it.
    }
    onNavigate("vitals", { returnTo: "inquiry" });
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

  function analyzeChatTranscript(transcript) {
    const symptoms = transcript.trim();
    if (!symptoms) {
      notify("请先完成一轮对话");
      return;
    }
    const nextForm = {
      symptoms_text: symptoms,
      duration: "对话问询已补充",
      used_medicines: "见对话记录",
      allergy_or_contraindication: "",
      scene_type: "家庭",
      include_vitals: true
    };
    setForm(nextForm);
    setAllergyChoice("无");
    setBlockedReason("");
    setStep("analyzing");
    window.setTimeout(() => {
      evaluateInquiry(nextForm)
        .then((data) => {
          setResult(data);
          setStep("result");
        })
        .catch((error) => {
          notify(error.message || "问询失败，请重试");
          setStep("start");
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
    setFollowupStage("duration");
    setResult(null);
    setFlowMode("guided");
    setVoiceMessage("");
    setVitalsMessage("");
    setBlockedReason("");
    try {
      window.sessionStorage.removeItem(draftKey);
    } catch {
      // sessionStorage is optional.
    }
  }

  return (
    <main className="inquiry-page" id="main-content">
      <section className="inquiry-flow-card" aria-label="AI 应急问询流程">
        {step === "start" ? (
          <>
            <div className="inquiry-mode-switch" aria-label="问询方式">
              <button type="button" className={flowMode === "guided" ? "active" : ""} onClick={() => setFlowMode("guided")}>
                引导问询
              </button>
              <button type="button" className={flowMode === "chat" ? "active" : ""} onClick={() => setFlowMode("chat")}>
                AI 对话
              </button>
            </div>
            {flowMode === "chat" ? (
              <InquiryChatStep
                notify={notify}
                onStructuredAnalyze={analyzeChatTranscript}
                onOpenVitals={handleOpenVitals}
              />
            ) : (
          <InquiryStartStep
            symptomsText={form.symptoms_text}
            listening={listening}
            voiceMessage={voiceMessage}
            onQuickSymptom={handleQuickSymptom}
            onVoiceInput={handleVoiceInput}
            onNext={handleNext}
          />
            )}
          </>
        ) : step === "followup" ? (
          <InquiryFollowupStep
            form={form}
            allergyChoice={allergyChoice}
            followupStage={followupStage}
            readingVitals={false}
            vitalsMessage={vitalsMessage}
            onFormChange={setForm}
            onAllergyChoice={setAllergyChoice}
            onStageChange={setFollowupStage}
            onReadVitals={handleOpenVitals}
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
    </main>
  );
}
