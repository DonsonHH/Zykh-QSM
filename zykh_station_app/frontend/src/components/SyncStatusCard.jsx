import React from "react";
import { CloudOff, RefreshCw } from "lucide-react";

export function SyncStatusCard({ syncStatus, syncing, onSync }) {
  const pending = syncStatus?.pending_count ?? 0;
  return (
    <section className="sync-status-card">
      <div>
        <p>同步状态</p>
        <h2>{syncStatus?.sync_status || "待同步"}</h2>
      </div>
      <div className="sync-status-meta">
        <span>
          <CloudOff size={19} aria-hidden="true" />
          {syncStatus?.network_mode || "弱网"}
        </span>
        <span>上次：{syncStatus?.last_sync_at || "未同步"}</span>
        <strong>{pending} 条待同步</strong>
      </div>
      <button type="button" onClick={onSync} disabled={syncing || pending === 0}>
        <RefreshCw size={21} aria-hidden="true" />
        {syncing ? "同步中..." : "模拟同步"}
      </button>
    </section>
  );
}
