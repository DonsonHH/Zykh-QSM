import React from "react";
import { Bot, HeartPulse, MessageCircle, ShieldCheck } from "lucide-react";

export function InquiryEntryCard({ inquiry, onStart }) {
  return (
    <section className="card task-card inquiry-entry-card">
      <div className="card-heading">
        <span className="card-icon purple" aria-hidden="true">
          <Bot size={34} strokeWidth={2.1} />
        </span>
        <div>
          <h2>{inquiry.title || "AI应急问询"}</h2>
        </div>
      </div>

      <div className="inquiry-visual-panel" aria-hidden="true">
        <article>
          <MessageCircle size={32} />
          <span>说出不适</span>
        </article>
        <article>
          <HeartPulse size={32} />
          <span>读取体征</span>
        </article>
        <article>
          <ShieldCheck size={32} />
          <span>安全核验</span>
        </article>
      </div>

      <button className="primary-action secondary" type="button" onClick={onStart}>
        {inquiry.action_label || "开始问询"}
      </button>
    </section>
  );
}
