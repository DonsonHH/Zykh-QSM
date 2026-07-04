import React from "react";
import { ClipboardCheck, PackageCheck } from "lucide-react";

const recordIcons = {
  取药确认: PackageCheck,
  取药记录: PackageCheck
};

export function RecentRecordList({ records }) {
  return (
    <section className="records-panel recent-records-panel">
      <div className="records-panel-heading">
        <p>最近记录</p>
        <h2>家庭取药记录</h2>
      </div>
      <div className="recent-record-list">
        {(records || []).slice(0, 5).map((record) => {
          const Icon = recordIcons[record.type] || ClipboardCheck;
          return (
            <article key={record.id} className="recent-record-row">
              <span className="recent-record-icon" aria-hidden="true">
                <Icon size={22} />
              </span>
              <time>{record.time}</time>
              <div>
                <strong>{record.title}</strong>
                <p>{record.description ? `数量 ${record.description}` : "已完成取药记录"}</p>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
