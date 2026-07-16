import React, { useEffect, useRef, useState } from "react";
import { ClipboardList, RefreshCw } from "lucide-react";
import { loadAdminLogs } from "../../api/admin.js";

export function AdminLogs({ notify, onSessionExpired }) {
  const [data, setData] = useState({ source: "backend", label: "后端服务", lines: [], sources: [] });
  const [loading, setLoading] = useState(false);
  const viewerRef = useRef(null);

  function load(source = data.source) {
    setLoading(true);
    loadAdminLogs(source)
      .then((next) => setData(next))
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        notify(error.message || "日志读取失败");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => { load("backend"); }, []);
  useEffect(() => {
    if (viewerRef.current) viewerRef.current.scrollTop = viewerRef.current.scrollHeight;
  }, [data.lines]);

  return (
    <div className="admin-view admin-logs-view">
      <div className="admin-page-heading">
        <div><h2>运行日志</h2><p>仅展示允许读取的本机日志，密钥和令牌会自动遮盖</p></div>
        <button type="button" className="admin-button secondary compact" onClick={() => load()} disabled={loading}><RefreshCw size={17} />刷新</button>
      </div>
      <section className="admin-log-shell">
        <aside>
          <header><ClipboardList size={18} /><strong>日志来源</strong></header>
          {data.sources.map((source) => (
            <button key={source.id} type="button" className={source.id === data.source ? "active" : ""} onClick={() => load(source.id)}>
              <span className={`admin-status-dot ${source.available ? "ok" : "warn"}`} />
              <strong>{source.label}</strong>
              <small>{source.available ? `${Math.ceil(source.size / 1024)} KB` : "无文件"}</small>
            </button>
          ))}
        </aside>
        <div className="admin-log-viewer" aria-busy={loading}>
          <header><strong>{data.label}</strong><span>{data.updated_at || ""}</span></header>
          <pre ref={viewerRef}>{data.lines.length ? data.lines.join("\n") : "当前日志暂无内容。"}</pre>
        </div>
      </section>
    </div>
  );
}
