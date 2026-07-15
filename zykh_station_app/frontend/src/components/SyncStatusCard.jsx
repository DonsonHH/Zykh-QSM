import React from "react";
import { RefreshCw } from "lucide-react";
import { isLocalNetworkMode } from "../utils/network.js";

function formatSyncTime(value) {
  if (!value) {
    return "刚刚";
  }

  const normalized = String(value).replace("T", " ");
  const match = normalized.match(/(?:\d{4}-)?(\d{2}-\d{2})\s+(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : normalized.slice(0, 16);
}

export function SyncStatusCard({ syncStatus, syncing, networkStatus, onSync }) {
  const localMode = isLocalNetworkMode(networkStatus);

  return (
    <section className="sync-status-card">
      <div>
        <h2>{localMode ? "本地记录" : syncStatus?.sync_status || "待同步"}</h2>
      </div>
      <div className="sync-status-meta">
        <span>{localMode ? "仅保存在本机" : `最近 ${formatSyncTime(syncStatus?.last_sync_at)}`}</span>
      </div>
      <button type="button" onClick={onSync} disabled={syncing}>
        <RefreshCw size={21} aria-hidden="true" />
        {syncing ? "同步中..." : localMode ? "刷新本地记录" : "尝试同步"}
      </button>
    </section>
  );
}
