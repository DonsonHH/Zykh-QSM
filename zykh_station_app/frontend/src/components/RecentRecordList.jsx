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
        <h2>家庭取药记录</h2>
        <span>{records?.length || 0} 条</span>
      </div>
      <div className="recent-record-list">
        {(records || []).map((record) => {
          const Icon = recordIcons[record.type] || ClipboardCheck;
          return (
            <article key={record.id} className="recent-record-row">
              <span className="recent-record-icon" aria-hidden="true">
                <Icon size={22} />
              </span>
              <div className="recent-record-person">
                <strong>{record.target_user || "游客"}</strong>
                <time>{record.time}</time>
              </div>
              <div className="recent-record-medicine">
                <strong>{record.title}</strong>
                <p>{record.description ? `取走 ${record.description}` : "已完成取药"}</p>
              </div>
              <em className={record.target_user_type === "guest" ? "record-guest-label" : "record-family-label"}>
                {record.target_user_type === "guest" ? "访客" : "家庭"}
              </em>
            </article>
          );
        })}
        {(!records || records.length === 0) && <p className="empty-list-note">暂无家庭取药记录</p>}
      </div>
    </section>
  );
}
