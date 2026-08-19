import React from "react";
import { CheckCircle2, LoaderCircle } from "lucide-react";

const progressItems = ["整理症状信息", "检查风险关键词", "核对过敏/禁忌", "匹配家庭分类柜药品"];

export function InquiryAnalyzingStep() {
  return (
    <section className="inquiry-analyzing-step" aria-live="polite">
      <div className="analyzing-icon" aria-hidden="true">
        <LoaderCircle size={42} />
      </div>
      <div className="inquiry-flow-heading centered">
        <p>用药安全核验</p>
        <h2>正在进行用药安全核验……</h2>
        <span>系统会输出结构化风险提示，不生成长篇聊天内容。</span>
      </div>
      <div className="analysis-progress-list">
        {progressItems.map((item) => (
          <span key={item}>
            <CheckCircle2 size={22} aria-hidden="true" />
            {item}
          </span>
        ))}
      </div>
    </section>
  );
}
