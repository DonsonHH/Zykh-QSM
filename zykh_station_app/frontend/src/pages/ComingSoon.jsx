import React from "react";
import { Construction } from "lucide-react";

const titles = {
  medicines: "药品",
  inquiry: "问询",
  records: "记录"
};

export function ComingSoon({ page }) {
  return (
    <main className="coming-soon-page" id="main-content">
      <section className="coming-panel">
        <Construction size={60} aria-hidden="true" />
        <span>下一阶段开发中</span>
        <h2>{titles[page] || "功能"}页面将在后续阶段接入</h2>
        <p>当前第一阶段只交付首页闭环，确保新架构干净稳定。</p>
      </section>
    </main>
  );
}
