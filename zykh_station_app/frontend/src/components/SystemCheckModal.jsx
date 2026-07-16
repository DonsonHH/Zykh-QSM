import React, { useEffect, useState } from "react";
import {
  Activity,
  BrainCircuit,
  Camera,
  CheckCircle2,
  Fingerprint,
  HeartPulse,
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
import { loadNetworkStatus, setNetworkMode, startQsm4g } from "../api/network.js";
import { isLocalNetworkMode } from "../utils/network.js";

const fallbackCheck = {
  qsm_mode: "mock",
  qsm_connected: false,
  qsm_status_ok: false,
  vitals_ok: false,
  local_camera_ok: false,
  local_camera_mode: "mock",
  local_camera_status: "mock",
  fingerprint_ok: false,
  fingerprint_status: "unavailable",
  fingerprint_bound_users: 0,
  dispense_dry_run: true,
  local_ai_ok: false,
  local_ai_model: "",
  local_ai_status: "unavailable",
  errors: [],
  warnings: ["系统检查暂不可用。"],
  recommendations: ["请稍后重新检查。"]
};

export function SystemCheckModal({ open, syncLabel, networkStatus, onNetworkStatusChange, onClose, notify }) {
  const [check, setCheck] = useState(fallbackCheck);
  const [network, setNetwork] = useState(networkStatus || null);
  const [audio, setAudio] = useState(null);
  const [volume, setVolume] = useState(230);
  const [loading, setLoading] = useState(false);
  const [testingAudio, setTestingAudio] = useState(false);
  const [switchingNetwork, setSwitchingNetwork] = useState(false);
  const [starting4g, setStarting4g] = useState(false);

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
        notify(mode === "sim" ? "已切换到 SIM 网络优先" : "已切换到离线模型");
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

  function run4gStart() {
    setStarting4g(true);
    startQsm4g()
      .then((result) => {
        if (result.network) {
          setNetwork(result.network);
          onNetworkStatusChange?.(result.network);
        }
        notify(result.ok ? "4G 联网检查完成" : "4G 联网未完成，请检查 SIM 和外设网络");
      })
      .catch((error) => notify(error.message || "4G 联网启动失败"))
      .finally(() => setStarting4g(false));
  }

  if (!open) {
    return null;
  }

  const alertItems = [...(check.errors || []), ...(check.warnings || [])];
  const modeLabel = check.qsm_mode === "real" ? "真实模式" : "本地模式";
  const currentNetwork = network || networkStatus || {};
  const networkLocal = isLocalNetworkMode(currentNetwork);
  const networkGood = !networkLocal && currentNetwork.signal === "good";
  const NetworkIcon = networkLocal ? WifiOff : Signal;
  const rows = [
    {
      icon: NetworkIcon,
      label: "网络状态",
      value: networkLocal ? "本地化运行" : currentNetwork.label || "SIM网络",
      ok: networkLocal ? Boolean(currentNetwork.local_ai?.ready) : networkGood || currentNetwork.simulated
    },
    {
      icon: BrainCircuit,
      label: "离线问询模型",
      value: check.local_ai_ok ? "可用" : "未就绪",
      ok: check.local_ai_ok
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
      label: "外设摄像头",
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
      icon: Fingerprint,
      label: "指纹模块",
      value: check.fingerprint_ok ? `${check.fingerprint_bound_users || 0} 人已绑定` : "不可用",
      ok: check.fingerprint_ok
    },
    {
      icon: ShieldCheck,
      label: "开柜控制",
      value: check.dispense_dry_run ? "未启用" : "真实联动",
      ok: !check.dispense_dry_run
    },
    {
      icon: Mic,
      label: "摄像头麦克风",
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
            <Activity size={32} />
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
                离线模型
              </button>
            </div>
            <button className="secondary-action settings-test-button" type="button" onClick={run4gStart} disabled={starting4g || networkLocal}>
              <Signal size={22} aria-hidden="true" />
              <span>{networkLocal ? "离线模型无需联网" : starting4g ? "联网中..." : "启动4G联网"}</span>
            </button>
            <label className="settings-range">
              <span>外放音量 SPK_VOL {volume}</span>
              <input type="range" min="0" max="255" step="5" value={volume} onChange={(event) => setVolume(Number(event.target.value))} />
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
            <p>摄像头：{check.local_camera_ok ? "可用，扫码页自动识别" : "不可用，请检查外设连接"}</p>
            <p>
              声音：
              {networkLocal ? "本地模式下仍可使用外设喇叭播放提示音。" : "外放由外设执行，本机生成的语音和提示音会发送到外设喇叭。"}
            </p>
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
