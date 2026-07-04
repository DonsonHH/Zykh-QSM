import React from "react";
import { CheckCircle2, RefreshCw } from "lucide-react";

export function SyncStatusCard({ syncStatus, syncing, onSync }) {
  return (
    <section className="sync-status-card">
      <div>
        <p>同步状态</p>
        <h2>{syncStatus?.sync_status || "待同步"}</h2>
      </div>
      <div className="sync-status-meta">
        <span>
          <CheckCircle2 size={19} aria-hidden="true" />
          {syncStatus?.network_mode || "家庭网络"}
        </span>
        <span>上次：{syncStatus?.last_sync_at || "刚刚"}</span>
      </div>
      <button type="button" onClick={onSync} disabled={syncing}>
        <RefreshCw size={21} aria-hidden="true" />
        {syncing ? "同步中..." : "尝试同步"}
      </button>
    </section>
  );
}
