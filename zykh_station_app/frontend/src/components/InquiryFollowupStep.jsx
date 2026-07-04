import React from "react";
import { Activity, ArrowLeft, CheckCircle2, SearchCheck } from "lucide-react";

const stages = ["duration", "medicine", "allergy", "vitals", "review"];
const stageIndex = Object.fromEntries(stages.map((stage, index) => [stage, index]));

const questions = {
  duration: {
    eyebrow: "第 1 步",
    title: "这种不舒服持续多久了？",
    hint: "选择最接近的时间，系统会判断是否存在持续加重风险。",
    options: [
      ["刚开始", "刚开始"],
      ["半天左右", "半天"],
      ["1天以上", "超过一天"],
      ["3天以上", "3天以上"]
    ]
  },
  medicine: {
    eyebrow: "第 2 步",
    title: "已经使用过药物吗？",
    hint: "如果不确定，请选择“不确定”，系统会提高安全提醒等级。",
    options: [
      ["未使用", "未使用"],
      ["已使用", "已使用过家庭常备药，具体不明"],
      ["不确定", "不确定"]
    ]
  },
  allergy: {
    eyebrow: "第 3 步",
    title: "有没有过敏或禁忌？",
    hint: "如果有明确过敏，请选择对应项；不确定时不会进入取药确认。",
    options: [
      ["无", ""],
      ["阿司匹林", "阿司匹林过敏或禁忌"],
      ["布洛芬", "布洛芬过敏或禁忌"],
      ["碘伏", "碘相关过敏或禁忌"],
      ["不确定", "不确定"]
    ]
  },
  vitals: {
    eyebrow: "第 4 步",
    title: "是否读取体温、心率和血氧？",
    hint: "建议按测量页引导读取体征，结果会一起交给系统分析。",
    options: [
      ["进入测量", "read"],
      ["暂时跳过", "skip"]
    ]
  }
};

export function InquiryFollowupStep({
  form,
  allergyChoice,
  followupStage,
  vitalsMessage,
  onFormChange,
  onAllergyChoice,
  onStageChange,
  onReadVitals,
  onBack,
  onAnalyze
}) {
  const currentStage = followupStage || "duration";
  const question = questions[currentStage];

  function goNext(nextStage) {
    window.setTimeout(() => onStageChange(nextStage), 120);
  }

  function choose(value) {
    if (currentStage === "duration") {
      onFormChange({ ...form, duration: value });
      goNext("medicine");
      return;
    }
    if (currentStage === "medicine") {
      onFormChange({ ...form, used_medicines: value });
      goNext("allergy");
      return;
    }
    if (currentStage === "allergy") {
      if (value === "") {
        onAllergyChoice("无");
        onFormChange({ ...form, allergy_or_contraindication: "" });
      } else if (value === "不确定") {
        onAllergyChoice("不确定");
        onFormChange({ ...form, allergy_or_contraindication: "不确定" });
      } else {
        onAllergyChoice("有");
        onFormChange({ ...form, allergy_or_contraindication: value });
      }
      goNext("vitals");
      return;
    }
    if (currentStage === "vitals") {
      if (value === "read") {
        onReadVitals();
        return;
      }
      onFormChange({ ...form, include_vitals: false });
      goNext("review");
    }
  }

  function backOneStep() {
    const index = stageIndex[currentStage] ?? 0;
    if (index <= 0) {
      onBack();
      return;
    }
    onStageChange(stages[index - 1]);
  }

  return (
    <section className="inquiry-followup-step guided">
      <div className="inquiry-flow-heading compact">
        <p>补充关键信息</p>
        <h2>{form.symptoms_text}</h2>
        <span>系统会逐步询问持续时间、用药情况、禁忌和体征。</span>
      </div>

      <div className="guided-progress" aria-label="问询进度">
        {stages.map((stage, index) => (
          <span key={stage} className={index <= (stageIndex[currentStage] ?? 0) ? "active" : ""} />
        ))}
      </div>

      {currentStage === "review" ? (
        <section className="guided-review-card">
          <p>信息已整理</p>
          <h3>可以开始安全分析</h3>
          <div className="guided-summary-grid">
            <span>持续：{form.duration || "未选择"}</span>
            <span>用药：{form.used_medicines || "未选择"}</span>
            <span>禁忌：{allergyChoice || "未选择"}</span>
            <span>体征：{form.include_vitals ? "已进入测量" : "未读取"}</span>
          </div>
          <small>{vitalsMessage || "若未读取体征，系统会基于当前信息进行保守分析。"}</small>
        </section>
      ) : (
        <section className="guided-question-card">
          <p>{question.eyebrow}</p>
          <h3>{question.title}</h3>
          <small>{question.hint}</small>
          <div className={`guided-option-grid ${currentStage}`}>
            {question.options.map(([label, value]) => (
              <button key={label} type="button" onClick={() => choose(value)}>
                {currentStage === "vitals" && value === "read" ? <Activity size={22} aria-hidden="true" /> : null}
                <span>{label}</span>
                <CheckCircle2 size={20} aria-hidden="true" />
              </button>
            ))}
          </div>
          {currentStage === "vitals" ? <em>{vitalsMessage || "测量页会引导额温、心率和血氧读取。"}</em> : null}
        </section>
      )}

      <div className="inquiry-step-actions">
        <button className="secondary-action" type="button" onClick={backOneStep}>
          <ArrowLeft size={22} aria-hidden="true" />
          返回
        </button>
        <button className="primary-action" type="button" onClick={onAnalyze} disabled={currentStage !== "review"}>
          <SearchCheck size={23} aria-hidden="true" />
          开始分析
        </button>
      </div>
    </section>
  );
}
