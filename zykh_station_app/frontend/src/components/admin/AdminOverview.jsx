import React from "react";
import { Boxes, Camera, CameraOff, CircleUserRound, Clock3, Database, HardDrive, RefreshCw, Router, Wifi } from "lucide-react";

function formatBytes(value) {
  if (!value) return "--";
  const gb = value / (1024 ** 3);
  return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`;
}

function StatusDot({ ok }) {
  return <span className={`admin-status-dot ${ok ? "ok" : "warn"}`} aria-label={ok ? "正常" : "需检查"} />;
}

export function AdminOverview({ data, loading, onRefresh }) {
  const host = data?.host || {};
  const counts = data?.counts || {};
  const network = data?.network || {};
  const devices = data?.devices || {};
  const metrics = [
    { label: "服务对象", value: counts.users ?? "--", icon: CircleUserRound, accent: "blue" },
    { label: "有库存仓位", value: counts.medicines ?? "--", icon: Boxes, accent: "green" },
    { label: "取药记录", value: counts.dispense_records ?? "--", icon: Database, accent: "violet" },
    { label: "待同步", value: counts.pending_sync ?? "--", icon: Clock3, accent: "orange" }
  ];
  const deviceRows = [
    ["外设网关", devices.gateway],
    ["摄像头", devices.camera],
    ["人脸识别", devices.face],
    ["指纹模块", devices.fingerprint],
    ["麦克风", devices.microphone]
  ];

  return (
    <div className="admin-view admin-overview-view">
      <div className="admin-page-heading">
        <div className="admin-section-entry-cue"><h2>运行概览</h2><p>主机、外设和业务数据的当前状态</p></div>
        <button type="button" className="admin-button secondary compact" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={17} aria-hidden="true" />
          刷新
        </button>
      </div>

      <section className="admin-metric-grid" aria-busy={loading}>
        {metrics.map(({ label, value, icon: Icon, accent }) => (
          <article key={label} className={`admin-metric ${accent}`}>
            <span><Icon size={20} aria-hidden="true" /></span>
            <div><strong>{value}</strong><small>{label}</small></div>
          </article>
        ))}
      </section>

      <section className="admin-overview-grid">
        <article className="admin-section-panel">
          <header><Router size={20} aria-hidden="true" /><h3>设备状态</h3></header>
          <div className="admin-status-list">
            {deviceRows.map(([label, status]) => (
              <div key={label}>
                <StatusDot ok={Boolean(status?.ok)} />
                <span>{label}</span>
                <strong>{status?.ok ? "可用" : status?.status === "configured" ? "已配置" : "需检查"}</strong>
              </div>
            ))}
          </div>
        </article>
        <article className="admin-section-panel">
          <header><HardDrive size={20} aria-hidden="true" /><h3>主机资源</h3></header>
          <dl className="admin-resource-list">
            <div><dt>运行时间</dt><dd>{host.uptime_seconds ? `${Math.floor(host.uptime_seconds / 3600)} 小时` : "--"}</dd></div>
            <div><dt>内存</dt><dd>{formatBytes(host.memory_used)} / {formatBytes(host.memory_total)}</dd></div>
            <div><dt>磁盘</dt><dd>{formatBytes(host.disk_used)} / {formatBytes(host.disk_total)}</dd></div>
            <div><dt>系统负载</dt><dd>{host.load?.join(" / ") || "--"}</dd></div>
          </dl>
        </article>
        <article className="admin-section-panel">
          <header><Wifi size={20} aria-hidden="true" /><h3>网络出口</h3></header>
          <dl className="admin-resource-list">
            <div><dt>当前链路</dt><dd>{network.transport || network.mode || "--"}</dd></div>
            <div><dt>Wi-Fi</dt><dd>{network.wifi_connected ? network.wifi_ssid || "已连接" : "未连接"}</dd></div>
            <div><dt>SIM</dt><dd>{network.sim_connected ? "已连接" : network.sim_present ? "已检测" : "未连接"}</dd></div>
            <div><dt>问询模式</dt><dd>{network.ai_mode === "cloud" ? "云端" : "本地"}</dd></div>
          </dl>
        </article>
      </section>

      <section className="admin-audit-panel">
        <header><h3>最近管理员操作</h3><span>{data?.generated_at || ""}</span></header>
        <div className="admin-audit-table">
          {(data?.recent_audit || []).length ? data.recent_audit.map((item) => (
            <div key={item.id}>
              <time>{item.created_at}</time><code>{item.action}</code><span>{item.target}</span><strong className={item.result === "success" ? "ok" : ""}>{item.result}</strong>
            </div>
          )) : <p className="admin-empty-state">暂无管理员操作记录</p>}
        </div>
      </section>

      <section className="admin-identity-archive-panel">
        <header>
          <div><Camera size={19} aria-hidden="true" /><h3>访客取药留档</h3></div>
          <span>{counts.identity_archives ?? 0} 张已保存</span>
        </header>
        <div className="admin-identity-archive-grid">
          {(data?.recent_dispense_archives || []).length ? data.recent_dispense_archives.map((item) => (
            <article key={item.id}>
              <div className="admin-archive-image">
                {item.thumbnail_data_url ? (
                  <img src={item.thumbnail_data_url} alt={`${item.target_user_name}取药留档`} />
                ) : (
                  <span><CameraOff size={26} aria-hidden="true" />画面未保存</span>
                )}
              </div>
              <div>
                <strong>{item.target_user_name}</strong>
                <span>{item.medicine_name}</span>
                <time>{item.captured_at}</time>
              </div>
            </article>
          )) : <p className="admin-empty-state">暂无访客取药照片</p>}
        </div>
      </section>
    </div>
  );
}
