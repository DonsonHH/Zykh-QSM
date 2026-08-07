import React from "react";
import { Cloud, RefreshCw } from "lucide-react";
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
  const synced = !localMode && syncStatus?.sync_status === "已同步" && Number(syncStatus?.pending_count || 0) === 0;
  const title = localMode
    ? "本地保存，实时同步已暂停"
    : synced
      ? "已实时同步"
      : `${syncStatus?.pending_count || 0} 条等待同步`;
  const detail = localMode
    ? "切换到联网模式后自动同步至微信小程序"
    : synced
      ? `最近同步 ${formatSyncTime(syncStatus?.last_sync_at)}`
      : "正在等待同步至微信小程序云端";

  return (
    <section className="sync-status-card">
      <div className="sync-cloud-heading">
        <span aria-hidden="true"><Cloud size={25} /></span>
        <div>
          <p>微信小程序云端</p>
          <h2>{title}</h2>
        </div>
      </div>
      <div className="sync-status-meta">
        <span>{detail}</span>
      </div>
      <button type="button" onClick={onSync} disabled={syncing}>
        <RefreshCw className={syncing ? "localized-loader" : undefined} size={21} aria-hidden="true" />
        {syncing ? "同步中..." : localMode ? "刷新状态" : "立即同步"}
      </button>
    </section>
  );
}
