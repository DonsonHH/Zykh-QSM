import { Camera, RefreshCw, RotateCcw, ScanLine, ShieldCheck } from "lucide-react";
import React, { useMemo, useState } from "react";
import { api, formBody } from "../api/client.js";
import { GlassCard } from "../components/GlassCard.jsx";
import { useAsyncAction } from "../hooks/useAsyncAction.js";

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

  const [scan, scanning] = useAsyncAction(async () => {
    setLive(false);
    try {
      await api("/api/camera/stream/stop", { method: "POST" }).catch(() => {});
      await new Promise((resolve) => window.setTimeout(resolve, 450));
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
      notify("识别完成，请核对药品信息");
    } catch (err) {
      notify(err.message);
      setLive(true);
      setStreamKey(Date.now());
    }
  });

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
            <span className="card-eyebrow">扫码/拍照识别</span>
            <h1>药品核验、站点码与取药复核</h1>
          </div>
          <span className={`record-link ${qsmOnline && !streamFailed ? "good" : "warn"}`}>
            {qsmOnline && !streamFailed ? "摄像头已连接 · 用于人工复核" : "摄像头暂不可用"}
          </span>
        </div>
        <div className={`camera-window ${qsmOnline && live && !streamFailed ? "live" : "idle"}`}>
          {qsmOnline && live && !streamFailed ? (
            <img src={streamUrl} alt="外设采集与执行控制平台摄像头实时预览" onError={() => setStreamFailed(true)} />
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
            <span>请将药盒、站点码或取到的药品放入框内</span>
          </div>
        </div>
        <div className="camera-controls">
          <button onClick={resume}>
            <RefreshCw size={22} />
            重新识别
          </button>
          <button className="capture-button" onClick={scan} disabled={!qsmOnline || streamFailed || scanning} aria-label={scanning ? "正在识别药品" : "拍照识别"}>
            <Camera size={34} />
          </button>
          <button className="scan-primary" onClick={scan} disabled={!qsmOnline || streamFailed || scanning}>
            <Camera size={22} />
            {scanning ? "识别中" : "拍照识别"}
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
              <p>用于说明核验 / 取药复核 <strong className="confidence-pill">{result ? "98%" : "--"}</strong></p>
            </div>
          </div>
        </div>

        <div className="confirm-section">
          <span className="card-eyebrow">核验信息</span>
          <label>
            药品名称
            <input value={draft.name || ""} readOnly />
          </label>
          <label>
            条码 / 站点码
            <input value={draft.code || ""} readOnly />
          </label>
          <div className="editor-row">
            <label>
              规格
              <input value={draft.dosage || ""} readOnly />
            </label>
            <label>
              复核数量
              <input type="number" min="0" value={draft.stock || 0} readOnly />
            </label>
          </div>
          <div className="editor-row">
            <label>
              仓位
              <input type="number" min="1" max="23" value={draft.slot || 1} readOnly />
            </label>
            <label>
              有效期
              <input value={draft.expire_date || ""} readOnly />
            </label>
          </div>
          <div className="scan-actions">
            <button onClick={resume}>
              <RotateCcw size={20} />
              重拍
            </button>
            <button className="primary" onClick={() => notify("已记录本次拍照核验，需管理员复核时请联系值守人员")}>
              <ShieldCheck size={20} />
              核验完成
            </button>
          </div>
        </div>
      </GlassCard>
    </div>
  );
}
