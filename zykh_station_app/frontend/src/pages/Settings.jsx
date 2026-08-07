import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Bug,
  Cloud,
  CloudOff,
  Clock3,
  LoaderCircle,
  Mic2,
  RadioTower,
  SunMedium,
  Volume2
} from "lucide-react";
import { loadBasicSettings, saveBasicSettings } from "../api/settings.js";
import { playBeep } from "../api/audio.js";
import { loadNetworkStatus } from "../api/network.js";
import { speakerGainToPercent, speakerPercentToGain } from "../utils/volume.js";

const DEFAULT_SETTINGS = {
  network_mode: "sim",
  speaker_volume: 230,
  microphone_volume: 70,
  display_brightness: 100,
  idle_timeout_seconds: 90
};

const EDITABLE_KEYS = [
  "network_mode",
  "speaker_volume",
  "microphone_volume",
  "display_brightness",
  "idle_timeout_seconds"
];
const AUTOSAVE_DELAY_MS = 900;

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
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState("loading");
  const [testing, setTesting] = useState(false);
  const valuesRef = useRef(DEFAULT_SETTINGS);
  const savedValuesRef = useRef(DEFAULT_SETTINGS);
  const saveQueueRef = useRef(Promise.resolve());
  const saveTimerRef = useRef(0);
  const mountedRef = useRef(true);
  const controlsLocked = loading || saveState === "saving";
  const speakerPercent = speakerGainToPercent(values.speaker_volume);

  const networkDescription = useMemo(() => {
    if (values.network_mode === "local" || values.network_mode === "offline") {
      return "本地图标已启用，小程序实时连接已暂停。";
    }
    return "显示实际网络状态，小程序保持实时连接。";
  }, [values.network_mode]);

  useEffect(() => {
    mountedRef.current = true;
    loadBasicSettings()
      .then((data) => {
        const next = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
        valuesRef.current = next;
        savedValuesRef.current = next;
        setValues(next);
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
          savedValuesRef.current = nextSaved;

          if (!mountedRef.current) return;
          setValues((current) => {
            const next = { ...current };
            EDITABLE_KEYS.forEach((key) => {
              if (Object.hasOwn(changes, key) && current[key] === snapshot[key]) next[key] = serverValues[key];
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
    playBeep(values.speaker_volume)
      .then((data) => notify(data.ok ? "外设测试音已播放" : data.message || "外放测试失败"))
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
            <RadioTower size={26} aria-hidden="true" />
            <h3>连接与同步</h3>
          </header>
          <p className="settings-panel-intro">选择终端对外显示和小程序同步状态。</p>
          <div className="network-mode-control" aria-label="连接与同步模式">
            <button
              type="button"
              className={values.network_mode === "sim" ? "active" : ""}
              disabled={controlsLocked}
              onClick={() => update("network_mode", "sim")}
            >
              <Cloud size={22} aria-hidden="true" />
              <span><strong>联网模式</strong><small>显示网络图标 · 实时同步</small></span>
            </button>
            <button
              type="button"
              className={values.network_mode !== "sim" ? "active" : ""}
              disabled={controlsLocked}
              onClick={() => update("network_mode", "local")}
            >
              <CloudOff size={22} aria-hidden="true" />
              <span><strong>本地模式</strong><small>显示本地图标 · 暂停同步</small></span>
            </button>
          </div>
          <div className="settings-mode-scope">
            <strong>仅改变显示与同步</strong>
            <span>不会切换实际 Wi-Fi、数据网络、AI 问询或语音路径。</span>
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
            value={speakerPercent}
            min={0}
            max={100}
            unit="%"
            disabled={controlsLocked}
            onChange={(value) => update("speaker_volume", speakerPercentToGain(value))}
          />
          <RangeSetting
            icon={Mic2}
            label="麦克风采集音量"
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
