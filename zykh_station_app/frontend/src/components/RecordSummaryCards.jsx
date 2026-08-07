import React from "react";
import { Database, RefreshCcw, Users } from "lucide-react";

const summaryItems = [
  { key: "today_service_users", label: "今日服务对象", unit: "人", icon: Users, tone: "blue" },
  { key: "pending_sync_count", label: "待同步", unit: "条", icon: RefreshCcw, tone: "orange" },
  { key: "local_record_count", label: "本地记录", unit: "条", icon: Database, tone: "purple" }
];

export function RecordSummaryCards({ summary }) {
  return (
    <section className="record-summary-grid" aria-label="服务记录摘要">
      {summaryItems.map((item) => {
        const Icon = item.icon;
        return (
          <article key={item.key} className={`record-summary-card ${item.tone}`}>
            <span className={item.key === "today_service_users" ? "page-entry-cue" : undefined} aria-hidden="true">
              <Icon size={24} />
            </span>
            <p>{item.label}</p>
            <strong>
              {summary?.[item.key] ?? "--"}
              <small>{item.unit}</small>
            </strong>
          </article>
        );
      })}
    </section>
  );
}
