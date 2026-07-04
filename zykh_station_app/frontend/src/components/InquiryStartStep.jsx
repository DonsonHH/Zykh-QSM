import React from "react";
import { ArrowRight, Keyboard, Mic } from "lucide-react";
import { SymptomQuickChips } from "./SymptomQuickChips.jsx";

export function InquiryStartStep({
  symptomsText,
  listening,
  voiceMessage,
  onSymptomsChange,
  onQuickSymptom,
  onVoiceInput,
  onNext
}) {
  return (
    <section className="inquiry-start-step">
      <div className="inquiry-flow-heading">
        <p>AI 应急问询</p>
        <h2>请告诉我你现在哪里不舒服</h2>
        <span>系统将进行风险提示与药品信息匹配。</span>
      </div>

      <button className="voice-entry-button" type="button" onClick={onVoiceInput} disabled={listening}>
        <Mic size={34} aria-hidden="true" />
        <strong>{listening ? "正在听取症状" : "点击说出症状"}</strong>
      </button>
      {voiceMessage ? <div className="voice-status">{voiceMessage}</div> : null}

      <label className="manual-symptom-box" htmlFor="inquiry-symptoms">
        <span>
          <Keyboard size={21} aria-hidden="true" />
          也可以手动输入症状
        </span>
        <textarea
          id="inquiry-symptoms"
          value={symptomsText}
          onChange={(event) => onSymptomsChange(event.target.value)}
          placeholder="例如：轻微腹泻、流涕、皮肤瘙痒"
          rows={3}
        />
      </label>

      <SymptomQuickChips selected={symptomsText} onSelect={onQuickSymptom} />

      <button className="primary-action inquiry-step-action" type="button" onClick={onNext}>
        下一步
        <ArrowRight size={24} aria-hidden="true" />
      </button>
    </section>
  );
}
