import React from "react";
import { ArrowRight, Bot, HeartPulse, MessageCircle, Mic2, ShieldCheck } from "lucide-react";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";

export function InquiryEntryCard({ inquiry, onStart }) {
  return (
    <section className="card task-card inquiry-entry-card">
      <div className="inquiry-assistant-stage">
        <div className="inquiry-assistant-portrait" aria-hidden="true">
          <StrokeDrawIcon icon={Bot} size={82} strokeWidth={1.75} mode="once" />
          <span className="inquiry-assistant-mic"><Mic2 size={24} /></span>
        </div>
        <div className="inquiry-assistant-content">
          <p>{inquiry.title || "AI应急问询"}</p>
          <strong>说出不适，我来逐步问询</strong>
          <div className="inquiry-capability-strip" aria-label="问询流程">
            <article>
              <MessageCircle size={25} aria-hidden="true" />
              <span>描述不适</span>
            </article>
            <article>
              <HeartPulse size={25} aria-hidden="true" />
              <span>读取体征</span>
            </article>
            <article>
              <ShieldCheck size={25} aria-hidden="true" />
              <span>安全核验</span>
            </article>
          </div>
        </div>
      </div>

      <button className="primary-action inquiry-entry-action" type="button" onClick={onStart}>
        <Mic2 size={25} aria-hidden="true" />
        <span>{inquiry.action_label || "开始问询"}</span>
        <ArrowRight size={25} aria-hidden="true" />
      </button>
    </section>
  );
}
