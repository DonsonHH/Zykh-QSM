import React, { useEffect, useRef, useState } from "react";
import { ClipboardList } from "lucide-react";
import { loadAdminLogs } from "../../api/admin.js";

export function AdminLogs({ notify, onSessionExpired }) {
  const [data, setData] = useState({ source: "backend", label: "后端服务", lines: [], sources: [] });
  const [loading, setLoading] = useState(false);
  const viewerRef = useRef(null);
  const sourceRef = useRef("backend");
  const pollingRef = useRef(false);
  const followTailRef = useRef(true);

  function load(source = sourceRef.current, silent = false) {
    if (pollingRef.current) return Promise.resolve();
    pollingRef.current = true;
    sourceRef.current = source;
    if (!silent) setLoading(true);
    return loadAdminLogs(source)
      .then((next) => {
        if (sourceRef.current === source) setData(next);
      })
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        if (!silent) notify(error.message || "日志读取失败");
      })
      .finally(() => {
        pollingRef.current = false;
        if (!silent) setLoading(false);
      });
  }

  useEffect(() => {
    load("backend");
    const timer = window.setInterval(() => load(sourceRef.current, true), 2000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (viewerRef.current && followTailRef.current) viewerRef.current.scrollTop = viewerRef.current.scrollHeight;
  }, [data.lines]);

  function handleScroll() {
    const viewer = viewerRef.current;
    if (!viewer) return;
    followTailRef.current = viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 36;
  }

  return (
    <div className="admin-view admin-logs-view">
      <div className="admin-page-heading">
        <div className="admin-section-entry-cue"><h2>运行日志</h2><p>仅展示允许读取的本机日志，密钥和令牌会自动遮盖</p></div>
        <div className="admin-live-log-state"><span />实时更新中</div>
      </div>
      <section className="admin-log-shell">
        <aside>
          <header><ClipboardList size={18} /><strong>日志来源</strong></header>
          {data.sources.map((source) => (
            <button key={source.id} type="button" className={source.id === data.source ? "active" : ""} onClick={() => { followTailRef.current = true; load(source.id); }}>
              <span className={`admin-status-dot ${source.available ? "ok" : "warn"}`} />
              <strong>{source.label}</strong>
              <small>{source.available ? `${Math.ceil(source.size / 1024)} KB` : "无文件"}</small>
            </button>
          ))}
        </aside>
        <div className="admin-log-viewer" aria-busy={loading}>
          <header><strong>{data.label}</strong><span>{data.updated_at || ""}</span></header>
          <pre ref={viewerRef} onScroll={handleScroll}>{data.lines.length ? data.lines.join("\n") : "当前日志暂无内容。"}</pre>
        </div>
      </section>
    </div>
  );
}
