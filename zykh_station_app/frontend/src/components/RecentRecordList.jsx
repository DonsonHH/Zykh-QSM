import React from "react";
import { Activity, ClipboardCheck, PackageCheck, QrCode, RefreshCw } from "lucide-react";

const recordIcons = {
  体征读取: Activity,
  AI应急问询: ClipboardCheck,
  药品扫码: QrCode,
  取药确认: PackageCheck,
  同步状态: RefreshCw
};

export function RecentRecordList({ records }) {
  return (
    <section className="records-panel recent-records-panel">
      <div className="records-panel-heading">
        <p>最近记录</p>
        <h2>本地服务记录</h2>
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
                <strong>{record.type}</strong>
                <p>{record.title}</p>
                <small>{record.description}</small>
              </div>
              <em className={record.sync_status === "已同步" ? "synced" : "pending"}>{record.sync_status}</em>
            </article>
          );
        })}
      </div>
    </section>
  );
}
