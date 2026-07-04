import React, { useEffect, useState } from "react";
import {
  Activity,
  Camera,
  CheckCircle2,
  HeartPulse,
  Loader2,
  Mic,
  RefreshCcw,
  Router,
  ShieldCheck,
  Signal,
  Volume2,
  WifiOff,
  X
} from "lucide-react";
import { loadHostAudioStatus, testAudioRelay } from "../api/audio.js";
import { loadDeviceCheck } from "../api/device.js";
import { loadNetworkStatus, setNetworkMode } from "../api/network.js";

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

export function SystemCheckModal({ open, syncLabel, networkStatus, onNetworkStatusChange, onClose, notify }) {
  const [check, setCheck] = useState(fallbackCheck);
  const [network, setNetwork] = useState(networkStatus || null);
  const [audio, setAudio] = useState(null);
  const [volume, setVolume] = useState(80);
  const [loading, setLoading] = useState(false);
  const [testingAudio, setTestingAudio] = useState(false);
  const [switchingNetwork, setSwitchingNetwork] = useState(false);

  function refresh() {
    setLoading(true);
    Promise.all([
      loadDeviceCheck().catch(() => fallbackCheck),
      loadNetworkStatus().catch(() => null),
      loadHostAudioStatus().catch(() => null)
    ])
      .then(([deviceCheck, nextNetwork, nextAudio]) => {
        setCheck(deviceCheck);
        if (nextNetwork) {
          setNetwork(nextNetwork);
          onNetworkStatusChange?.(nextNetwork);
        }
        setAudio(nextAudio);
      })
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

  function switchNetwork(mode) {
    setSwitchingNetwork(true);
    setNetworkMode(mode)
      .then((nextNetwork) => {
        setNetwork(nextNetwork);
        onNetworkStatusChange?.(nextNetwork);
        notify(mode === "sim" ? "已切换到 SIM 网络优先" : "已切换到本地兜底");
      })
      .catch((error) => notify(error.message || "网络模式切换失败"))
      .finally(() => setSwitchingNetwork(false));
  }

  function runAudioTest() {
    setTestingAudio(true);
    testAudioRelay({ text: "外放测试，声音链路正常。", volume })
      .then((result) => notify(result.ok ? "已请求外设外放测试" : result.message || "外放测试失败"))
      .catch((error) => notify(error.message || "外放测试失败"))
      .finally(() => setTestingAudio(false));
  }

  if (!open) {
    return null;
  }

  const alertItems = [...(check.errors || []), ...(check.warnings || [])];
  const modeLabel = check.qsm_mode === "real" ? "真实模式" : "本地模式";
  const currentNetwork = network || networkStatus || {};
  const networkGood = currentNetwork.signal === "good";
  const networkLocal = currentNetwork.mode === "local";
  const NetworkIcon = networkLocal ? WifiOff : Signal;
  const rows = [
    {
      icon: NetworkIcon,
      label: "网络状态",
      value: networkLocal ? "本地兜底" : currentNetwork.label || "SIM网络",
      ok: networkGood || currentNetwork.simulated
    },
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
      icon: Mic,
      label: "本机麦克风",
      value: audio?.microphone_available ? "可用" : "待检测",
      ok: Boolean(audio?.microphone_available)
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

        <div className="system-check-notes settings-notes">
          <div className="settings-control-panel">
            <strong>网络与声音</strong>
            <div className="settings-segment" aria-label="网络模式">
              <button type="button" className={!networkLocal ? "active" : ""} disabled={switchingNetwork} onClick={() => switchNetwork("sim")}>
                SIM网络
              </button>
              <button type="button" className={networkLocal ? "active" : ""} disabled={switchingNetwork} onClick={() => switchNetwork("local")}>
                本地兜底
              </button>
            </div>
            <label className="settings-range">
              <span>外放音量 {volume}%</span>
              <input type="range" min="20" max="100" step="5" value={volume} onChange={(event) => setVolume(Number(event.target.value))} />
            </label>
            <button className="secondary-action settings-test-button" type="button" onClick={runAudioTest} disabled={testingAudio}>
              <Volume2 size={22} aria-hidden="true" />
              <span>{testingAudio ? "测试中..." : "外放测试"}</span>
            </button>
          </div>
          <div className="settings-control-panel">
            <strong>设备调试</strong>
            <p>
              麦克风：{audio?.microphone_available ? audio.microphones?.[0]?.label || "可用" : "未检测到"}
            </p>
            <p>摄像头：{check.local_camera_ok ? "可用，扫码页自动识别" : "不可用，请检查连接"}</p>
            <p>声音：外放由外设执行，原声实时转发需板端增加音频播放接口。</p>
          </div>
          <div className="settings-control-panel">
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
