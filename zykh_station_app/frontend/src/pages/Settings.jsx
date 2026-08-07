import React, { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  CircleCheck,
  Clock3,
  LoaderCircle,
  Mic2,
  SunMedium,
  Volume2,
  Wifi,
  WifiOff,
  Wrench
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
  const offlineMode = values.network_mode === "local" || values.network_mode === "offline";
  const networkDescription = offlineMode
    ? "设备当前处于断网模式"
    : "设备已联网，网络服务运行正常";
  const saveLabel = saveState === "loading"
    ? "正在读取"
    : saveState === "pending"
      ? "等待保存"
      : saveState === "saving"
        ? "正在保存"
        : saveState === "error"
          ? "保存失败"
          : "设置已保存";

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
          {saveState === "saved" ? <CircleCheck size={18} aria-hidden="true" /> : null}
          {saveLabel}
        </span>
        <button className="admin-entry-button" type="button" onClick={() => onNavigate("admin")}>
          <Wrench size={20} aria-hidden="true" />
          设备调试
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
          <header className="settings-section-heading">
            <span className="settings-section-icon"><Wifi size={25} aria-hidden="true" /></span>
            <div>
              <h3>网络</h3>
              <p>选择设备的网络状态</p>
            </div>
          </header>
          <div className="network-mode-control" role="radiogroup" aria-label="网络模式">
            <button
              type="button"
              className={`network-mode-button online ${!offlineMode ? "active" : ""}`}
              role="radio"
              aria-checked={!offlineMode}
              disabled={controlsLocked}
              onClick={() => update("network_mode", "sim")}
            >
              <span className="network-mode-icon"><Wifi size={25} aria-hidden="true" /></span>
              <span className="network-mode-copy"><strong>联网模式</strong><small>网络连接正常</small></span>
              <span className="network-mode-check" aria-hidden="true"><Check size={17} /></span>
            </button>
            <button
              type="button"
              className={`network-mode-button offline ${offlineMode ? "active" : ""}`}
              role="radio"
              aria-checked={offlineMode}
              disabled={controlsLocked}
              onClick={() => update("network_mode", "local")}
            >
              <span className="network-mode-icon"><WifiOff size={25} aria-hidden="true" /></span>
              <span className="network-mode-copy"><strong>断网模式</strong><small>设备保持离线</small></span>
              <span className="network-mode-check" aria-hidden="true"><Check size={17} /></span>
            </button>
          </div>
        </article>

        <article className="basic-settings-panel sound-panel">
          <header className="settings-section-heading">
            <span className="settings-section-icon"><Volume2 size={25} aria-hidden="true" /></span>
            <div>
              <h3>声音</h3>
              <p>调整播报与收音音量</p>
            </div>
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
          <header className="settings-section-heading">
            <span className="settings-section-icon"><SunMedium size={25} aria-hidden="true" /></span>
            <div>
              <h3>屏幕</h3>
              <p>调整显示与息屏时间</p>
            </div>
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
