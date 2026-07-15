import React from "react";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { isLocalNetworkMode } from "../utils/network.js";

export function SyncStatusCard({ syncStatus, syncing, networkStatus, onSync }) {
  const localMode = isLocalNetworkMode(networkStatus);

  return (
    <section className="sync-status-card">
      <div>
        <p>同步状态</p>
        <h2>{localMode ? "本地记录" : syncStatus?.sync_status || "待同步"}</h2>
      </div>
      <div className="sync-status-meta">
        <span>
          <CheckCircle2 size={19} aria-hidden="true" />
          {localMode ? "本地模式" : syncStatus?.network_mode || "家庭网络"}
        </span>
        <span>{localMode ? "仅保存在本机" : `上次：${syncStatus?.last_sync_at || "刚刚"}`}</span>
      </div>
      <button type="button" onClick={onSync} disabled={syncing}>
        <RefreshCw size={21} aria-hidden="true" />
        {syncing ? "同步中..." : localMode ? "刷新本地记录" : "尝试同步"}
      </button>
    </section>
  );
}
