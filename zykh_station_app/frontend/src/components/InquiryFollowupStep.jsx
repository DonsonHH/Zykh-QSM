import React from "react";
import { Activity, ArrowLeft, SearchCheck } from "lucide-react";
import { FollowupOptionGroup } from "./FollowupOptionGroup.jsx";

const durationOptions = [
  { label: "刚开始", value: "刚开始" },
  { label: "半天", value: "半天" },
  { label: "1天以上", value: "超过一天" },
  { label: "3天以上", value: "3天以上" }
];

const usedMedicineOptions = ["未使用", "已使用", "不确定"];
const allergyOptions = ["无", "有", "不确定"];

export function InquiryFollowupStep({
  form,
  allergyChoice,
  readingVitals,
  vitalsMessage,
  onFormChange,
  onAllergyChoice,
  onReadVitals,
  onBack,
  onAnalyze
}) {
  function update(field, value) {
    onFormChange({ ...form, [field]: value });
  }

  function updateAllergyChoice(value) {
    onAllergyChoice(value);
    if (value === "无") {
      update("allergy_or_contraindication", "");
    } else if (value === "不确定") {
      update("allergy_or_contraindication", "不确定");
    } else {
      update("allergy_or_contraindication", "");
    }
  }

  return (
    <section className="inquiry-followup-step">
      <div className="inquiry-flow-heading compact">
        <p>补充关键信息</p>
        <h2>{form.symptoms_text}</h2>
        <span>选择最接近的情况，系统会据此进行用药安全核验。</span>
      </div>

      <div className="followup-grid">
        <FollowupOptionGroup
          title="持续时间"
          options={durationOptions}
          value={form.duration}
          onChange={(value) => update("duration", value)}
        />

        <FollowupOptionGroup
          title="已用药情况"
          options={usedMedicineOptions}
          value={form.used_medicines}
          onChange={(value) => update("used_medicines", value)}
        />

        <FollowupOptionGroup
          title="过敏/禁忌"
          options={allergyOptions}
          value={allergyChoice}
          onChange={updateAllergyChoice}
        >
          {allergyChoice === "有" ? (
            <input
              className="followup-text-input"
              value={form.allergy_or_contraindication}
              onChange={(event) => update("allergy_or_contraindication", event.target.value)}
              placeholder="请输入过敏或禁忌信息"
            />
          ) : null}
        </FollowupOptionGroup>

        <section className="followup-option-group vitals-group">
          <h3>体征读取</h3>
          <div className="followup-option-row">
            <button type="button" className={form.include_vitals ? "active" : ""} onClick={onReadVitals} disabled={readingVitals}>
              <Activity size={20} aria-hidden="true" />
              {readingVitals ? "读取中" : "进入测量"}
            </button>
            <button type="button" className={!form.include_vitals ? "active soft" : "soft"} onClick={() => update("include_vitals", false)}>
              跳过
            </button>
          </div>
          <p className="vitals-message">{vitalsMessage || "体征可选，将进入独立测量页完成引导。"}</p>
        </section>
      </div>

      <div className="inquiry-step-actions">
        <button className="secondary-action" type="button" onClick={onBack}>
          <ArrowLeft size={22} aria-hidden="true" />
          返回
        </button>
        <button className="primary-action" type="button" onClick={onAnalyze}>
          <SearchCheck size={23} aria-hidden="true" />
          开始分析
        </button>
      </div>
    </section>
  );
}
