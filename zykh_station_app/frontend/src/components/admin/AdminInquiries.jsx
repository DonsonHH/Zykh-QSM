import React, { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, RefreshCw } from "lucide-react";
import { loadAdminInquiries } from "../../api/admin.js";

export function AdminInquiries({ notify, onSessionExpired }) {
  const [data, setData] = useState({ sessions: [], repeated_question_sessions: 0 });
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(false);
  const selected = useMemo(
    () => data.sessions.find((session) => session.session_id === selectedId) || data.sessions[0] || null,
    [data.sessions, selectedId]
  );

  function refresh(silent = false) {
    if (!silent) setLoading(true);
    return loadAdminInquiries()
      .then((next) => {
        setData(next);
        setSelectedId((current) => next.sessions.some((session) => session.session_id === current)
          ? current
          : next.sessions[0]?.session_id || "");
      })
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        if (!silent) notify(error.message || "问询历史读取失败");
      })
      .finally(() => { if (!silent) setLoading(false); });
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => refresh(true), 4000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="admin-view admin-inquiries-view">
      <div className="admin-page-heading">
        <div><h2>问询调试</h2><p>查看原始转写、结构化信息、体征快照与系统动作</p></div>
        <div className="admin-heading-actions">
          {data.repeated_question_sessions ? <span className="admin-inquiry-warning"><AlertTriangle size={15} />{data.repeated_question_sessions} 个会话出现重复追问</span> : null}
          <button type="button" className="admin-button secondary compact" onClick={() => refresh()} disabled={loading}><RefreshCw size={17} />刷新</button>
        </div>
      </div>
      <div className="admin-inquiry-shell">
        <aside className="admin-inquiry-list">
          {data.sessions.map((session) => (
            <button key={session.session_id} type="button" className={selected?.session_id === session.session_id ? "active" : ""} onClick={() => setSelectedId(session.session_id)}>
              <span><strong>{session.title}</strong><time>{session.updated_at}</time></span>
              <small>{session.stage} · {session.next_action} · {session.source}</small>
            </button>
          ))}
          {!data.sessions.length ? <p className="admin-empty-state">暂无问询会话</p> : null}
        </aside>
        {selected ? <InquiryDebugDetail session={selected} /> : <section className="admin-inquiry-detail"><p className="admin-empty-state">请选择一条问询会话</p></section>}
      </div>
    </div>
  );
}

function InquiryDebugDetail({ session }) {
  const extracted = session.extracted_information || {};
  const vitals = session.vitals || {};
  return (
    <section className="admin-inquiry-detail">
      <header>
        <div><strong>{session.user_name}</strong><span>{session.session_id}</span></div>
        <em className={session.risk_level || "pending"}>{session.risk_level || "pending"}</em>
      </header>
      <div className="admin-inquiry-facts">
        <Fact
          label="病例观察"
          value={(extracted.observations || []).filter((item) => item.status === "present").map((item) => item.concept).join("、") || "未提取"}
        />
        <Fact label="持续时间" value={extracted.duration || "未确认"} />
        <Fact label="已用药" value={extracted.used_medicines || "未确认"} />
        <Fact label="过敏禁忌" value={extracted.allergy_or_contraindication || "未确认"} />
        <Fact label="体征快照" value={formatVitals(vitals)} />
        <Fact label="系统动作" value={`${session.next_action} · ${session.action_status}`} />
      </div>
      <div className="admin-inquiry-reasoning"><Activity size={16} /><span>{session.reasoning_summary || session.action_reason || "暂无模型摘要"}</span></div>
      <div className="admin-inquiry-thread">
        {(session.messages || []).map((message) => (
          <article key={message.id} className={message.role}>
            <header><strong>{message.role === "user" ? "用户" : "系统"}</strong><time>{message.created_at}</time><em>{message.source}</em></header>
            <p>{message.content}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function Fact({ label, value }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function formatVitals(vitals) {
  const core = vitals.core || vitals;
  const temperature = usableValue(core.temperature);
  const heartRate = usableValue(core.heart_rate);
  const spo2 = usableValue(core.spo2);
  if (!temperature || !heartRate || !spo2) return "未完成";
  return `${temperature}℃ · ${heartRate}次/分 · ${spo2}%`;
}

function usableValue(metric) {
  if (metric && typeof metric === "object") {
    return metric.usable === true ? metric.value : null;
  }
  return metric;
}
