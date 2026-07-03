import React from "react";
import { Activity, Mic, SearchCheck } from "lucide-react";

const scenes = ["村镇", "家庭", "高原", "景区"];

export function InquiryForm({ form, submitting, onChange, onSubmit, onPlaceholder }) {
  function updateField(field, value) {
    onChange({ ...form, [field]: value });
  }

  return (
    <form className="inquiry-form-panel" onSubmit={onSubmit}>
      <div className="inquiry-panel-heading">
        <p>输入信息</p>
        <h2>AI应急问询</h2>
      </div>

      <label className="field-stack" htmlFor="symptoms-text">
        <span>症状</span>
        <textarea
          id="symptoms-text"
          value={form.symptoms_text}
          onChange={(event) => updateField("symptoms_text", event.target.value)}
          placeholder="例如：轻微腹泻、流涕、皮肤瘙痒"
          rows={3}
          required
        />
      </label>

      <div className="field-row">
        <label className="field-stack" htmlFor="duration">
          <span>持续时间</span>
          <input
            id="duration"
            value={form.duration}
            onChange={(event) => updateField("duration", event.target.value)}
            placeholder="如 半天"
          />
        </label>
        <label className="field-stack" htmlFor="scene-type">
          <span>场景</span>
          <select id="scene-type" value={form.scene_type} onChange={(event) => updateField("scene_type", event.target.value)}>
            {scenes.map((scene) => (
              <option key={scene} value={scene}>
                {scene}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="field-stack" htmlFor="used-medicines">
        <span>已用药</span>
        <input
          id="used-medicines"
          value={form.used_medicines}
          onChange={(event) => updateField("used_medicines", event.target.value)}
          placeholder="未使用可留空"
        />
      </label>

      <label className="field-stack" htmlFor="allergy-text">
        <span>过敏/禁忌</span>
        <input
          id="allergy-text"
          value={form.allergy_or_contraindication}
          onChange={(event) => updateField("allergy_or_contraindication", event.target.value)}
          placeholder="如 阿司匹林过敏"
        />
      </label>

      <div className="inquiry-tool-row">
        <button type="button" onClick={() => onPlaceholder("语音输入将在后续阶段接入")}>
          <Mic size={21} aria-hidden="true" />
          语音输入
        </button>
        <button
          type="button"
          onClick={() => {
            updateField("include_vitals", true);
            onPlaceholder("体征读取本阶段为占位，已标记需要参考体征");
          }}
        >
          <Activity size={21} aria-hidden="true" />
          读取体征
        </button>
      </div>

      <button className="primary-action inquiry-submit" type="submit" disabled={submitting}>
        <SearchCheck size={24} aria-hidden="true" />
        {submitting ? "问询中..." : "开始问询"}
      </button>
    </form>
  );
}
