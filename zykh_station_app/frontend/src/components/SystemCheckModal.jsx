import React, { useEffect, useState } from "react";
import { Activity, Camera, CheckCircle2, HeartPulse, Loader2, RefreshCcw, Router, ShieldCheck, X } from "lucide-react";
import { loadDeviceCheck } from "../api/device.js";

const fallbackCheck = {
  qsm_mode: "mock",
  qsm_connected: false,
  qsm_status_ok: false,
  vitals_ok: false,
  local_camera_ok: false,
  local_camera_mode: "mock",
  local_camera_status: "mock",
  dispense_dry_run: true,
  errors: [],
  warnings: ["系统检查暂不可用。"],
  recommendations: ["请稍后重新检查。"]
};

export function SystemCheckModal({ open, syncLabel, onClose, notify }) {
  const [check, setCheck] = useState(fallbackCheck);
  const [loading, setLoading] = useState(false);

  function refresh() {
    setLoading(true);
    loadDeviceCheck()
      .then(setCheck)
      .catch((error) => {
        setCheck(fallbackCheck);
        notify(error.message || "系统检查失败");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (open) {
      refresh();
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const alertItems = [...(check.errors || []), ...(check.warnings || [])];
  const modeLabel = check.qsm_mode === "real" ? "真实模式" : "本地模式";
  const rows = [
    {
      icon: Activity,
      label: "当前模式",
      value: modeLabel,
      ok: check.qsm_mode === "mock" || check.qsm_connected
    },
    {
      icon: Router,
      label: "外设网关连接",
      value: check.qsm_connected ? "已连接" : "未连接",
      ok: check.qsm_connected || check.qsm_mode === "mock"
    },
    {
      icon: Camera,
      label: "本机摄像头",
      value: check.local_camera_ok ? "可用" : "不可用",
      ok: check.local_camera_ok
    },
    {
      icon: HeartPulse,
      label: "体征模块",
      value: check.vitals_ok ? "可用" : "不可用",
      ok: check.vitals_ok
    },
    {
      icon: ShieldCheck,
      label: "开柜控制",
      value: check.dispense_dry_run ? "未启用" : "真实联动",
      ok: !check.dispense_dry_run
    },
    {
      icon: CheckCircle2,
      label: "同步状态",
      value: syncLabel || "本地记录",
      ok: true
    }
  ];

  return (
    <div className="system-check-layer" role="presentation">
      <section className="system-check-modal" role="dialog" aria-modal="true" aria-labelledby="system-check-title">
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭系统检查">
          <X size={24} aria-hidden="true" />
        </button>

        <div className="system-check-heading">
          <span aria-hidden="true">
            {loading ? <Loader2 size={32} className="spin-icon" /> : <Activity size={32} />}
          </span>
          <div>
            <p>外设检查</p>
            <h2 id="system-check-title">系统检查</h2>
          </div>
        </div>

        <div className="system-check-grid">
          {rows.map((row) => {
            const Icon = row.icon;
            return (
              <article key={row.label} className={row.ok ? "ok" : "warn"}>
                <Icon size={24} aria-hidden="true" />
                <span>{row.label}</span>
                <strong>{row.value}</strong>
              </article>
            );
          })}
        </div>

        <div className="system-check-notes">
          <div>
            <strong>提示</strong>
            {alertItems.length > 0 ? (
              <ul>
                {alertItems.slice(0, 3).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>当前检查项可用于真实外设流程。</p>
            )}
          </div>
          <div>
            <strong>建议</strong>
            <ul>
              {(check.recommendations || []).slice(0, 3).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        <div className="system-check-actions">
          <button className="secondary-action" type="button" onClick={onClose}>
            返回终端
          </button>
          <button className="primary-action" type="button" onClick={refresh} disabled={loading}>
            <RefreshCcw size={22} aria-hidden="true" />
            <span>{loading ? "检查中..." : "重新检查"}</span>
          </button>
        </div>
      </section>
    </div>
  );
}
