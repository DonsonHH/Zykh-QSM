import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Bug,
  Clock3,
  LoaderCircle,
  Mic2,
  RadioTower,
  SunMedium,
  Volume2,
  Wifi
} from "lucide-react";
import { loadBasicSettings, saveBasicSettings } from "../api/settings.js";
import { testAudioRelay } from "../api/audio.js";
import { loadNetworkStatus } from "../api/network.js";

const DEFAULT_SETTINGS = {
  wifi_enabled: true,
  sim_enabled: true,
  network_mode: "sim",
  speaker_volume: 230,
  microphone_volume: 70,
  display_brightness: 100,
  idle_timeout_seconds: 90,
  wifi_ssid: "",
  sim_connected: false,
  sim_operator: "",
  sim_operator_code: "",
  sim_phone_number: "",
  microphone_available: false
};

const EDITABLE_KEYS = [
  "wifi_enabled",
  "sim_enabled",
  "network_mode",
  "speaker_volume",
  "microphone_volume",
  "display_brightness",
  "idle_timeout_seconds"
];
const STATUS_KEYS = ["wifi_ssid", "sim_connected", "sim_operator", "sim_operator_code", "sim_phone_number", "microphone_available"];
const AUTOSAVE_DELAY_MS = 900;

function SettingsSwitch({ checked, onChange, label, disabled = false }) {
  return (
    <button
      className={`settings-switch ${checked ? "is-on" : ""}`}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span aria-hidden="true" />
    </button>
  );
}

function RangeSetting({ icon: Icon, label, value, min, max, unit, onChange, disabled = false }) {
  return (
    <label className="basic-settings-range">
      <span className="basic-settings-range-label">
        <Icon size={24} aria-hidden="true" />
        <strong>{label}</strong>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <output>{value}{unit}</output>
    </label>
  );
}

export function Settings({ notify, onNavigate, onNetworkStatusChange }) {
  const [values, setValues] = useState(DEFAULT_SETTINGS);
  const [simDisplayEnabled, setSimDisplayEnabled] = useState(DEFAULT_SETTINGS.sim_enabled);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState("loading");
  const [testing, setTesting] = useState(false);
  const valuesRef = useRef(DEFAULT_SETTINGS);
  const savedValuesRef = useRef(DEFAULT_SETTINGS);
  const saveQueueRef = useRef(Promise.resolve());
  const saveTimerRef = useRef(0);
  const mountedRef = useRef(true);
  const controlsLocked = loading || saveState === "saving";

  const networkDescription = useMemo(() => {
    if (values.network_mode === "local" || values.network_mode === "offline") {
      return "当前为本地模式，语音输入与播报在设备内完成。";
    }
    if (values.wifi_enabled && values.wifi_ssid) {
      return `已连接 ${values.wifi_ssid}`;
    }
    if (values.sim_enabled && values.sim_connected) {
      return "Wi-Fi 不可用时可使用数据网络。";
    }
    return "当前未检测到可用联网链路。";
  }, [values]);

  useEffect(() => {
    mountedRef.current = true;
    loadBasicSettings()
      .then((data) => {
        const next = {
          ...DEFAULT_SETTINGS,
          ...(data.settings || {}),
          sim_operator: data.settings?.sim_operator || "",
          sim_operator_code: data.settings?.sim_operator_code || "",
          sim_phone_number: data.settings?.sim_phone_number || ""
        };
        valuesRef.current = next;
        savedValuesRef.current = next;
        setValues(next);
        setSimDisplayEnabled(Boolean(next.sim_enabled));
        setSaveState("saved");
      })
      .catch((error) => {
        setSaveState("error");
        notify(error.message || "设置读取失败");
      })
      .finally(() => setLoading(false));

    return () => {
      mountedRef.current = false;
      window.clearTimeout(saveTimerRef.current);
    };
  }, [notify]);

  function update(key, value) {
    setValues((current) => {
      const next = { ...current, [key]: value };
      valuesRef.current = next;
      return next;
    });
  }

  function enqueueSave() {
    saveQueueRef.current = saveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        const snapshot = { ...valuesRef.current };
        const changes = Object.fromEntries(
          EDITABLE_KEYS
            .filter((key) => snapshot[key] !== savedValuesRef.current[key])
            .map((key) => [key, snapshot[key]])
        );
        if (!Object.keys(changes).length) {
          if (mountedRef.current) setSaveState("saved");
          return;
        }

        if (mountedRef.current) setSaveState("saving");
        try {
          const data = await saveBasicSettings(changes);
          const serverValues = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
          const nextSaved = { ...savedValuesRef.current };
          EDITABLE_KEYS.forEach((key) => {
            if (Object.hasOwn(changes, key)) nextSaved[key] = serverValues[key];
          });
          STATUS_KEYS.forEach((key) => {
            nextSaved[key] = serverValues[key];
          });
          savedValuesRef.current = nextSaved;

          if (!mountedRef.current) return;
          setValues((current) => {
            const next = { ...current };
            EDITABLE_KEYS.forEach((key) => {
              if (Object.hasOwn(changes, key) && current[key] === snapshot[key]) next[key] = serverValues[key];
            });
            STATUS_KEYS.forEach((key) => {
              next[key] = serverValues[key];
            });
            valuesRef.current = next;
            return next;
          });
          setSaveState("saved");
          window.dispatchEvent(new CustomEvent("zykh:settings-updated", { detail: data.settings }));
          loadNetworkStatus().then((status) => onNetworkStatusChange?.(status)).catch(() => undefined);
          if (data.warnings?.length) notify(data.warnings[0]);
        } catch (error) {
          if (mountedRef.current) {
            setSaveState("error");
            notify(error.message || "设置保存失败");
          }
        }
      });
  }

  useEffect(() => {
    if (loading) return undefined;
    const changed = EDITABLE_KEYS.some((key) => values[key] !== savedValuesRef.current[key]);
    window.clearTimeout(saveTimerRef.current);
    if (!changed) {
      if (saveState === "pending") setSaveState("saved");
      return undefined;
    }
    setSaveState("pending");
    saveTimerRef.current = window.setTimeout(enqueueSave, AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(saveTimerRef.current);
  }, [loading, values]);

  function testSpeaker() {
    setTesting(true);
    testAudioRelay({ volume: values.speaker_volume, text: "声音测试完成。" })
      .then((data) => notify(data.ok ? "测试声音已播放" : data.message || "外放测试失败"))
      .catch((error) => notify(error.message || "外放测试失败"))
      .finally(() => setTesting(false));
  }

  return (
    <main className="basic-settings-page" id="main-content">
      <header className="basic-settings-header">
        <button className="icon-action" type="button" onClick={() => onNavigate("home")} aria-label="返回首页">
          <ArrowLeft size={24} aria-hidden="true" />
        </button>
        <div className="basic-settings-title">
          <h2>终端设置</h2>
          <span>{loading ? "正在读取设备" : networkDescription}</span>
        </div>
        <span className={`settings-autosave-state ${saveState}`} role="status" aria-live="polite">
          {saveState === "saving" || saveState === "loading" ? <LoaderCircle size={18} className="spin" aria-hidden="true" /> : null}
          {saveState === "loading" ? "正在读取" : saveState === "pending" ? "等待自动保存" : saveState === "saving" ? "正在自动保存" : saveState === "error" ? "自动保存失败" : "已自动保存"}
        </span>
        <button className="admin-entry-button" type="button" onClick={() => onNavigate("admin")}>
          <Bug size={20} aria-hidden="true" />
          管理员调试
        </button>
      </header>

      <section className={`basic-settings-grid ${controlsLocked ? "is-loading" : ""}`} aria-busy={controlsLocked}>
        {controlsLocked ? (
          <div className="settings-loading-shield" role="status" aria-live="polite">
            <LoaderCircle size={34} className="spin" aria-hidden="true" />
            <strong>{loading ? "正在读取设备设置" : "正在应用设备设置"}</strong>
            <span>{loading ? "读取完成后即可修改" : "完成后将自动恢复操作"}</span>
          </div>
        ) : null}
        <article className="basic-settings-panel network-panel">
          <header>
            <Wifi size={26} aria-hidden="true" />
            <h3>网络与运行模式</h3>
          </header>
          <div className="basic-setting-toggle-row">
            <div>
              <strong>Wi-Fi</strong>
              <span>{values.wifi_ssid || (values.wifi_enabled ? "已开启" : "已关闭")}</span>
            </div>
            <SettingsSwitch checked={values.wifi_enabled} disabled={controlsLocked} onChange={(next) => update("wifi_enabled", next)} label="切换 Wi-Fi" />
          </div>
          <div className="basic-setting-toggle-row">
            <div>
              <strong>数据网络</strong>
              <span>{!simDisplayEnabled ? "已关闭" : values.sim_connected ? `${values.sim_operator || "移动网络"}已连接` : "等待数据网络"}</span>
              <small>{values.sim_phone_number || "模块未提供号码"}{values.sim_operator_code ? ` · ${values.sim_operator_code}` : ""}</small>
            </div>
            <SettingsSwitch checked={simDisplayEnabled} disabled={controlsLocked} onChange={setSimDisplayEnabled} label="切换数据网络显示" />
          </div>
          <div className="network-mode-control" aria-label="问询运行模式">
            <button
              type="button"
              className={values.network_mode === "sim" ? "active" : ""}
              disabled={controlsLocked}
              onClick={() => update("network_mode", "sim")}
            >
              <RadioTower size={20} aria-hidden="true" />
              联网优先
            </button>
            <button
              type="button"
              className={values.network_mode !== "sim" ? "active" : ""}
              disabled={controlsLocked}
              onClick={() => update("network_mode", "local")}
            >
              本地模式
            </button>
          </div>
        </article>

        <article className="basic-settings-panel sound-panel">
          <header>
            <Volume2 size={26} aria-hidden="true" />
            <h3>声音</h3>
          </header>
          <RangeSetting
            icon={Volume2}
            label="外放音量"
            value={values.speaker_volume}
            min={0}
            max={255}
            unit=""
            disabled={controlsLocked}
            onChange={(value) => update("speaker_volume", value)}
          />
          <RangeSetting
            icon={Mic2}
            label="麦克风增益"
            value={values.microphone_volume}
            min={0}
            max={100}
            unit="%"
            disabled={controlsLocked}
            onChange={(value) => update("microphone_volume", value)}
          />
          <button className="settings-test-sound" type="button" onClick={testSpeaker} disabled={controlsLocked || testing}>
            <Volume2 size={21} aria-hidden="true" />
            {testing ? "正在播放" : "测试外放"}
          </button>
        </article>

        <article className="basic-settings-panel display-panel">
          <header>
            <SunMedium size={26} aria-hidden="true" />
            <h3>屏幕</h3>
          </header>
          <RangeSetting
            icon={SunMedium}
            label="显示亮度"
            value={values.display_brightness}
            min={20}
            max={100}
            unit="%"
            disabled={controlsLocked}
            onChange={(value) => update("display_brightness", value)}
          />
          <label className="idle-time-setting">
            <span>
              <Clock3 size={24} aria-hidden="true" />
              <strong>自动息屏</strong>
            </span>
            <select disabled={controlsLocked} value={values.idle_timeout_seconds} onChange={(event) => update("idle_timeout_seconds", Number(event.target.value))}>
              <option value={30}>30 秒</option>
              <option value={60}>1 分钟</option>
              <option value={90}>1 分 30 秒</option>
              <option value={180}>3 分钟</option>
              <option value={300}>5 分钟</option>
              <option value={0}>不自动息屏</option>
            </select>
          </label>
        </article>
      </section>
    </main>
  );
}
