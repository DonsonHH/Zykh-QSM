import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Bug,
  Clock3,
  Mic2,
  RadioTower,
  RefreshCw,
  Save,
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
  microphone_available: false
};

function SettingsSwitch({ checked, onChange, label }) {
  return (
    <button
      className={`settings-switch ${checked ? "is-on" : ""}`}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
    >
      <span aria-hidden="true" />
    </button>
  );
}

function RangeSetting({ icon: Icon, label, value, min, max, unit, onChange }) {
  return (
    <label className="basic-settings-range">
      <span className="basic-settings-range-label">
        <Icon size={24} aria-hidden="true" />
        <strong>{label}</strong>
      </span>
      <input type="range" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <output>{value}{unit}</output>
    </label>
  );
}

export function Settings({ notify, onNavigate, onNetworkStatusChange }) {
  const [values, setValues] = useState(DEFAULT_SETTINGS);
  const [savedValues, setSavedValues] = useState(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [dirty, setDirty] = useState(false);

  const networkDescription = useMemo(() => {
    if (values.network_mode === "local" || values.network_mode === "offline") {
      return "当前使用本地问询能力，联网链路保持原状态。";
    }
    if (values.wifi_enabled && values.wifi_ssid) {
      return `已连接 ${values.wifi_ssid}`;
    }
    if (values.sim_enabled && values.sim_connected) {
      return "Wi-Fi 不可用时可使用 SIM 备用链路。";
    }
    return "当前未检测到可用联网链路。";
  }, [values]);

  function refresh() {
    setLoading(true);
    loadBasicSettings()
      .then((data) => {
        const next = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
        setValues(next);
        setSavedValues(next);
        setDirty(false);
      })
      .catch((error) => notify(error.message || "设置读取失败"))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  function update(key, value) {
    setValues((current) => ({ ...current, [key]: value }));
    setDirty(true);
  }

  function save() {
    if (saving) return;
    setSaving(true);
    const editableKeys = [
      "wifi_enabled",
      "sim_enabled",
      "network_mode",
      "speaker_volume",
      "microphone_volume",
      "display_brightness",
      "idle_timeout_seconds"
    ];
    const changes = Object.fromEntries(editableKeys.filter((key) => values[key] !== savedValues[key]).map((key) => [key, values[key]]));
    saveBasicSettings(changes)
      .then((data) => {
        const next = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
        setValues(next);
        setSavedValues(next);
        setDirty(false);
        window.dispatchEvent(new CustomEvent("zykh:settings-updated", { detail: data.settings }));
        loadNetworkStatus().then((status) => onNetworkStatusChange?.(status)).catch(() => undefined);
        notify(data.warnings?.length ? data.warnings[0] : "设置已应用");
      })
      .catch((error) => notify(error.message || "设置保存失败"))
      .finally(() => setSaving(false));
  }

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
        <button className="admin-entry-button" type="button" onClick={() => onNavigate("admin")}>
          <Bug size={20} aria-hidden="true" />
          管理员调试
        </button>
      </header>

      <section className="basic-settings-grid" aria-busy={loading}>
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
            <SettingsSwitch checked={values.wifi_enabled} onChange={(next) => update("wifi_enabled", next)} label="切换 Wi-Fi" />
          </div>
          <div className="basic-setting-toggle-row">
            <div>
              <strong>SIM 备用网络</strong>
              <span>{values.sim_connected ? "外设网络已连接" : values.sim_enabled ? "等待外设网络" : "已关闭"}</span>
            </div>
            <SettingsSwitch checked={values.sim_enabled} onChange={(next) => update("sim_enabled", next)} label="切换 SIM 网络" />
          </div>
          <div className="network-mode-control" aria-label="问询运行模式">
            <button
              type="button"
              className={values.network_mode === "sim" ? "active" : ""}
              onClick={() => update("network_mode", "sim")}
            >
              <RadioTower size={20} aria-hidden="true" />
              联网优先
            </button>
            <button
              type="button"
              className={values.network_mode !== "sim" ? "active" : ""}
              onClick={() => update("network_mode", "local")}
            >
              本地问询
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
            onChange={(value) => update("speaker_volume", value)}
          />
          <RangeSetting
            icon={Mic2}
            label="麦克风增益"
            value={values.microphone_volume}
            min={0}
            max={100}
            unit="%"
            onChange={(value) => update("microphone_volume", value)}
          />
          <button className="settings-test-sound" type="button" onClick={testSpeaker} disabled={testing}>
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
            onChange={(value) => update("display_brightness", value)}
          />
          <label className="idle-time-setting">
            <span>
              <Clock3 size={24} aria-hidden="true" />
              <strong>自动息屏</strong>
            </span>
            <select value={values.idle_timeout_seconds} onChange={(event) => update("idle_timeout_seconds", Number(event.target.value))}>
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

      <footer className="basic-settings-footer">
        <button type="button" className="settings-refresh-button" onClick={refresh} disabled={loading} title="重新读取设置">
          <RefreshCw size={22} aria-hidden="true" />
          重新读取
        </button>
        <button type="button" className="settings-save-button" onClick={save} disabled={!dirty || saving || loading}>
          <Save size={22} aria-hidden="true" />
          {saving ? "正在应用" : dirty ? "应用设置" : "设置已保存"}
        </button>
      </footer>
    </main>
  );
}
