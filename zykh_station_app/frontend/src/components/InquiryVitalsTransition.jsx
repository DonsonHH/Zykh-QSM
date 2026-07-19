import React from "react";
import { Activity, HeartPulse, ShieldCheck } from "lucide-react";

export function InquiryVitalsTransition({ reason }) {
  return (
    <section className="inquiry-vitals-transition" role="status" aria-live="polite">
      <div className="inquiry-vitals-transition-visual" aria-hidden="true">
        <span className="inquiry-vitals-transition-orbit" />
        <HeartPulse size={104} strokeWidth={1.8} />
      </div>
      <div className="inquiry-vitals-transition-copy">
        <span><ShieldCheck size={21} aria-hidden="true" />语音引导已完成</span>
        <h2>即将开始体征测量</h2>
        <p>{reason || "本次体征将帮助 AI 更准确地理解你刚才描述的不适。"}</p>
      </div>
      <div className="inquiry-vitals-transition-progress" aria-hidden="true">
        <i />
      </div>
      <div className="inquiry-vitals-transition-metrics" aria-hidden="true">
        <span><Activity size={22} />心率</span>
        <span><Activity size={22} />血氧</span>
        <span><Activity size={22} />额温</span>
      </div>
    </section>
  );
}
