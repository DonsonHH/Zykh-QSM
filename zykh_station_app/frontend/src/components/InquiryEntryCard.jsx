import React from "react";
import { Bot, CheckCircle2, ShieldCheck } from "lucide-react";

const fallbackLines = [
  "整理症状和禁忌信息",
  "给出风险提示与药品信息匹配",
  "不做诊断或处方"
];

export function InquiryEntryCard({ inquiry, onStart }) {
  return (
    <section className="card task-card inquiry-entry-card">
      <div className="card-heading">
        <span className="card-icon purple" aria-hidden="true">
          <Bot size={34} strokeWidth={2.1} />
        </span>
        <div>
          <p className="eyebrow">应急问询</p>
          <h2>{inquiry.title || "AI应急问询"}</h2>
        </div>
      </div>

      <ul className="inquiry-list" aria-label="问询范围">
        {fallbackLines.map((line) => (
          <li key={line}>
            <CheckCircle2 size={24} aria-hidden="true" />
            <span>{line}</span>
          </li>
        ))}
      </ul>

      <div className="safety-note">
        <ShieldCheck size={24} aria-hidden="true" />
        <span>先核验风险，再进入取药确认。</span>
      </div>

      <button className="primary-action secondary" type="button" onClick={onStart}>
        {inquiry.action_label || "开始问询"}
      </button>
    </section>
  );
}
