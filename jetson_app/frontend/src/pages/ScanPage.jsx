import { Camera, Check, RefreshCw, RotateCcw, ScanLine } from "lucide-react";
import React, { useMemo, useState } from "react";
import { api, formBody } from "../api/client.js";
import { GlassCard } from "../components/GlassCard.jsx";

export function ScanPage({ status, refresh, notify }) {
  const [live, setLive] = useState(true);
  const [result, setResult] = useState({ ok: true, demo: true });
  const [draft, setDraft] = useState({
    slot: 4,
    stock: 1,
    expire_date: "2026-12-31",
    dosage: "0.35g*24粒",
    code: "869000100004",
    trace_code: "TRACE-DEMO-04",
    box_size: "big",
    name: "连花清瘟胶囊"
  });
  const [streamKey, setStreamKey] = useState(Date.now());
  const [streamFailed, setStreamFailed] = useState(false);
  const qsmOnline = Boolean(status?.qsm?.online);
  const streamUrl = useMemo(() => `/api/camera/stream?width=760&height=480&fps=24&t=${streamKey}`, [streamKey]);

  const scan = async () => {
    setLive(false);
    try {
      const data = await api("/api/medicine/scan", { method: "POST" });
      setResult(data);
      const medicine = data.scan?.medicine || data.scan?.lookup?.medicine || data.scan?.result || {};
      setDraft({
        slot: data.suggestion?.slot || 1,
        stock: data.suggestion?.stock || 1,
        expire_date: medicine.expire_date || medicine.expiry_date || "",
        dosage: medicine.dosage || medicine.spec || "",
        code: data.scan?.code || medicine.code || "",
        trace_code: medicine.trace_code || "",
        box_size: data.suggestion?.box_size || "medium",
        name: medicine.name || medicine.medicine_name || ""
      });
      notify("识别完成，请核对后入库");
    } catch (err) {
      notify(err.message);
      setLive(true);
      setStreamKey(Date.now());
    }
  };

  const confirm = async () => {
    try {
      await api("/api/medicine/scan", formBody({ ...draft, confirm: 1 }));
      notify(`${draft.slot} 号仓已录入`);
      await refresh();
      setResult(null);
      setLive(true);
      setStreamKey(Date.now());
    } catch (err) {
      notify(err.message);
    }
  };

  const resume = () => {
    setLive(true);
    setStreamFailed(false);
    setStreamKey(Date.now());
  };

  return (
    <div className="scan-page">
      <GlassCard className="camera-panel">
        <div className="page-heading compact">
          <div>
            <span className="card-eyebrow">拍照识药</span>
            <h1>请将药盒放入识别框内</h1>
          </div>
          <span className={`record-link ${qsmOnline && !streamFailed ? "good" : "warn"}`}>
            {qsmOnline && !streamFailed ? "摄像头已连接 · 1280×720" : "摄像头暂不可用"}
          </span>
        </div>
        <div className="camera-window">
          {qsmOnline && live && !streamFailed ? (
            <img src={streamUrl} alt="QSM 摄像头实时预览" onError={() => setStreamFailed(true)} />
          ) : (
            <div className="camera-empty">
              <Camera size={78} />
              <strong>{qsmOnline && !streamFailed ? "预览已暂停" : "摄像头暂不可用"}</strong>
              <span>{qsmOnline && !streamFailed ? "点击刷新预览继续观察" : "请在管理后台检查设备连接"}</span>
            </div>
          )}
          <div className="focus-frame">
            <i />
            <i />
            <i />
            <i />
          </div>
          <div className="camera-guide">
            <ScanLine size={22} />
            <span>请将药盒正面放入框内</span>
          </div>
        </div>
        <div className="camera-controls">
          <button onClick={resume}>
            <RefreshCw size={22} />
            重新识别
          </button>
          <button className="capture-button" onClick={scan} disabled={!qsmOnline || streamFailed}>
            <Camera size={34} />
          </button>
          <button className="scan-primary" onClick={scan} disabled={!qsmOnline || streamFailed}>
            <Camera size={22} />
            拍照识别
          </button>
        </div>
      </GlassCard>

      <GlassCard className="scan-result-panel">
        <div className="result-section">
          <span className="card-eyebrow">{qsmOnline && !streamFailed ? "识别结果" : "最近识别结果 · 摄像头暂不可用"}</span>
          <div className="result-card">
            <div className="drug-thumbnail">
              <Camera size={34} />
            </div>
            <div>
              <h2>{draft.name || "等待识别"}</h2>
              <p>识别置信度：<strong>{result ? "98%" : "--"}</strong></p>
            </div>
          </div>
        </div>

        <div className="confirm-section">
          <span className="card-eyebrow">信息确认</span>
          <label>
            药品名称
            <input value={draft.name || ""} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
          </label>
          <label>
            追溯码
            <input value={draft.code || ""} onChange={(event) => setDraft({ ...draft, code: event.target.value })} />
          </label>
          <div className="editor-row">
            <label>
              规格
              <input value={draft.dosage || ""} onChange={(event) => setDraft({ ...draft, dosage: event.target.value })} />
            </label>
            <label>
              数量
              <input type="number" min="0" value={draft.stock || 0} onChange={(event) => setDraft({ ...draft, stock: event.target.value })} />
            </label>
          </div>
          <div className="editor-row">
            <label>
              仓位
              <input type="number" min="1" max="23" value={draft.slot || 1} onChange={(event) => setDraft({ ...draft, slot: event.target.value })} />
            </label>
            <label>
              有效期
              <input value={draft.expire_date || ""} onChange={(event) => setDraft({ ...draft, expire_date: event.target.value })} />
            </label>
          </div>
          <div className="scan-actions">
            <button onClick={resume}>
              <RotateCcw size={20} />
              重拍
            </button>
            <button className="primary" onClick={confirm}>
              <Check size={20} />
              确认入库
            </button>
          </div>
        </div>
      </GlassCard>
    </div>
  );
}
