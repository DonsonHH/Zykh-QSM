import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Fingerprint,
  Gauge,
  HeartPulse,
  MoveVertical,
  ScanFace,
  ShieldCheck,
  Thermometer,
  Waves,
  Wind
} from "lucide-react";
import { loadQsmVitals } from "../api/qsm.js";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";

const measurementSeconds = 18;

export function Vitals({ notify, onNavigate, returnPage = "home" }) {
  const [phase, setPhase] = useState("idle");
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [countdown, setCountdown] = useState(measurementSeconds);
  const requestIdRef = useRef(0);

  const returnLabel = returnPage === "inquiry" ? "返回问询" : "返回首页";
  const status = useMemo(() => describeVitals(result, errorMessage, phase), [errorMessage, phase, result]);
  const auxiliaryMetrics = useMemo(() => buildAuxiliaryMetrics(result), [result]);
  const hasFingerTemperature = hasReading(result?.body_temperature);
  const elapsedSeconds = measurementSeconds - countdown;
  const progressPercent =
    phase === "done" ? 100 : phase === "measuring" ? Math.min(100, Math.round((elapsedSeconds / measurementSeconds) * 100)) : 0;

  useEffect(() => {
    if (phase !== "measuring") {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setCountdown((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  function handleMeasure() {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setPhase("measuring");
    setCountdown(measurementSeconds);
    setResult(null);
    setErrorMessage("");
    loadQsmVitals()
      .then((data) => {
        if (requestId !== requestIdRef.current) {
          return;
        }
        setResult(data);
        setPhase("done");
        if (data.ok === false || data.status === "unavailable") {
          const message = data.error_message || "体征设备暂不可用，可稍后重试。";
          setErrorMessage(message);
          notify(message);
          return;
        }
        if (!hasCoreVitals(data)) {
          notify(missingCoreVitalsMessage(data));
          return;
        }
        try {
          window.sessionStorage.setItem("zykh-latest-vitals", JSON.stringify(data));
        } catch {
          // sessionStorage is optional.
        }
        notify("体征测量已完成");
      })
      .catch((error) => {
        if (requestId !== requestIdRef.current) {
          return;
        }
        const message = error.message || "体征设备暂不可用，可稍后重试。";
        setErrorMessage(message);
        setPhase("done");
        notify(message);
      });
  }

  function handleBack() {
    onNavigate(returnPage === "inquiry" ? "inquiry" : "home");
  }

  return (
    <main className="vitals-page" id="main-content">
      <section className="vitals-guide-panel">
        <div className="vitals-page-heading">
          <button className="icon-action" type="button" onClick={handleBack} aria-label={returnLabel}>
            <ArrowLeft size={24} aria-hidden="true" />
          </button>
          <div>
            <p>身体状态</p>
            <h2>{phase === "measuring" ? "正在测量" : result ? "测量结果" : "一键测量"}</h2>
          </div>
        </div>

        <div className={`vitals-visual-guide ${phase}`}>
          <article className="vitals-pose-card forehead">
            <div className="vitals-pose-graphic" aria-hidden="true">
              <span className="vitals-sensor-cap" />
              {phase === "measuring" ? (
                <StrokeDrawIcon icon={ScanFace} size={76} strokeWidth={2} mode="yoyo" />
              ) : (
                <ScanFace size={76} />
              )}
              <span className="vitals-distance-mark">
                <MoveVertical size={22} />
                20cm
              </span>
            </div>
            <div className="vitals-pose-label">
              <span className="vitals-pose-icon forehead" aria-hidden="true">
                <Thermometer size={24} />
              </span>
              <div>
                <strong>额温</strong>
                <span>屏幕上方 · 约20cm</span>
              </div>
            </div>
          </article>

          <article className="vitals-pose-card fingertip">
            <div className="vitals-pose-graphic" aria-hidden="true">
              {phase === "measuring" ? (
                <StrokeDrawIcon icon={Fingerprint} size={78} strokeWidth={2} mode="yoyo" />
              ) : (
                <Fingerprint size={78} />
              )}
            </div>
            <div className="vitals-pose-label">
              <span className="vitals-pose-icon fingertip" aria-hidden="true">
                <HeartPulse size={24} />
              </span>
              <div>
                <strong>心率 · 血氧</strong>
                <span>右前方 · 指尖感应区</span>
              </div>
            </div>
          </article>
        </div>

        <div className="vitals-action-row">
          <button className="primary-action" type="button" onClick={handleMeasure} disabled={phase === "measuring"}>
            <Activity size={24} aria-hidden="true" />
            <span>{phase === "measuring" ? `正在测量 · ${countdown}秒` : result ? "重新测量" : "开始测量"}</span>
          </button>
          <button className="secondary-action compact" type="button" onClick={handleBack}>
            {returnLabel}
          </button>
        </div>
      </section>

      <section
        className={`vitals-result-panel ${status.tone} ${auxiliaryMetrics.length ? "has-reference" : "core-only"}`}
        aria-label="体征测量结果"
      >
        <div className="vitals-result-heading">
          <span aria-hidden="true">
            <Thermometer size={34} />
          </span>
          <div>
            <p>实时结果</p>
            <h2 aria-live="polite">{status.title}</h2>
          </div>
        </div>

        {result ? (
          <>
            <div className={`vitals-metric-grid ${hasFingerTemperature ? "four" : "three"}`}>
              <Metric
                icon={HeartPulse}
                label="心率"
                value={formatMetric(result?.heart_rate, "次/分", phase, result, 0)}
                tone="heart"
                primary
              />
              <Metric
                icon={Activity}
                label="血氧"
                value={formatMetric(result?.spo2, "%", phase, result, 0)}
                tone="oxygen"
                primary
              />
              <Metric
                icon={Thermometer}
                label="额温"
                value={formatMetric(result?.temperature, "℃", phase, result, 1)}
                tone="forehead"
              />
              {hasFingerTemperature ? (
                <Metric
                  icon={Fingerprint}
                  label="指温参考"
                  value={formatMetric(result?.body_temperature, "℃", phase, result, 2)}
                  tone="finger"
                />
              ) : null}
            </div>

            {auxiliaryMetrics.length ? (
              <div
                className={`vitals-reference-grid count-${auxiliaryMetrics.length}`}
                aria-label="本次读取到的辅助体征"
              >
                {auxiliaryMetrics.map(({ icon, label, value }) => (
                  <ReferenceMetric key={label} icon={icon} label={label} value={value} />
                ))}
              </div>
            ) : null}

            <div className="vitals-status-card">
              <span aria-hidden="true">
                <ShieldCheck size={24} />
              </span>
              <div>
                <strong>{status.summary}</strong>
                <p>{status.detail}</p>
              </div>
            </div>
          </>
        ) : (
          <ResultPlaceholder phase={phase} countdown={countdown} progressPercent={progressPercent} />
        )}
      </section>
    </main>
  );
}

function ResultPlaceholder({ phase, countdown, progressPercent }) {
  const measuring = phase === "measuring";
  const previewItems = [
    { label: "心率", icon: HeartPulse },
    { label: "血氧", icon: Activity },
    { label: "体温", icon: Thermometer },
    { label: "身体参考", icon: Waves }
  ];

  return (
    <div className={`vitals-result-placeholder ${measuring ? "measuring" : "idle"}`}>
      <div className={`vitals-result-visual ${measuring ? "is-measuring" : ""}`} aria-hidden="true">
        {measuring ? (
          <span className="vitals-heart-pulses">
            <i />
            <i />
          </span>
        ) : null}
        <span className="vitals-result-heart">
          <HeartPulse size={54} strokeWidth={1.9} />
        </span>
      </div>
      <div className="vitals-placeholder-copy">
        <p>{measuring ? "数据采集中" : "本次测量"}</p>
        <h3>{measuring ? `${countdown} 秒` : "心率、血氧与体温"}</h3>
        <span>{measuring ? "读数稳定后自动完成" : "点击左侧开始测量"}</span>
      </div>
      <div className="vitals-preview-items" aria-label="可测量项目">
        {previewItems.map(({ label, icon: Icon }) => (
          <span key={label}>
            <Icon size={20} aria-hidden="true" />
            {label}
          </span>
        ))}
      </div>
      <div className="vitals-placeholder-progress" aria-hidden="true">
        <i style={{ width: `${measuring ? progressPercent : 0}%` }} />
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value, tone, primary = false }) {
  return (
    <article className={`vitals-metric ${tone} ${primary ? "primary" : ""}`}>
      <span className="vitals-metric-icon" aria-hidden="true">
        <Icon size={25} />
      </span>
      <span className="vitals-metric-label">{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function ReferenceMetric({ icon: Icon, label, value }) {
  return (
    <article className="vitals-reference-metric">
      <Icon size={20} aria-hidden="true" />
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function formatMetric(value, unit, phase, result, fractionDigits = 0) {
  if (phase === "measuring") {
    return "采集中";
  }
  if (!result) {
    return "尚未测量";
  }
  if (value === null || value === undefined || Number.isNaN(Number(value)) || Number(value) <= 0) {
    return "未读取";
  }
  const numeric = Number(value);
  return `${numeric.toFixed(fractionDigits)}${unit}`;
}

function formatPressure(result) {
  const systolic = Number(result?.systolic_pressure);
  const diastolic = Number(result?.diastolic_pressure);
  return `${Math.round(systolic)}/${Math.round(diastolic)}`;
}

function buildAuxiliaryMetrics(result) {
  if (!result) {
    return [];
  }
  const metrics = [];
  if (hasReading(result.systolic_pressure) && hasReading(result.diastolic_pressure)) {
    metrics.push({ icon: Gauge, label: "血压", value: formatPressure(result) });
  }
  if (hasReading(result.respiratory_rate)) {
    metrics.push({ icon: Wind, label: "呼吸", value: `${Math.round(Number(result.respiratory_rate))}次/分` });
  }
  if (hasReading(result.hrv_sdnn)) {
    metrics.push({ icon: Waves, label: "HRV", value: `${Math.round(Number(result.hrv_sdnn))}ms` });
  }
  return metrics;
}

function describeVitals(result, errorMessage, phase) {
  if (phase === "measuring") {
    return {
      tone: "active",
      title: "正在采集",
      summary: "信号采集中",
      detail: "正在形成稳定读数"
    };
  }

  if (!result && !errorMessage) {
    return {
      tone: "idle",
      title: "结果预览",
      summary: "准备测量",
      detail: "准备好后开始"
    };
  }

  if (errorMessage || result?.ok === false || result?.status === "unavailable") {
    return {
      tone: "warn",
      title: "设备暂不可用",
      summary: "本次未完成",
      detail: errorMessage || result?.error_message || "请检查设备后重试"
    };
  }

  if (hasCoreVitals(result)) {
    const referenceCount = buildAuxiliaryMetrics(result).length;
    return {
      tone: "good",
      title: "测量完成",
      summary: "心率、血氧与额温已记录",
      detail: referenceCount ? `同时读取到 ${referenceCount} 项身体参考` : "核心体征读取完整"
    };
  }

  if (result?.quality === "error") {
    return {
      tone: "warn",
      title: "心率血氧模块异常",
      summary: "请重新放置手指",
      detail: humanVitalsMessage(result, "请将指腹贴合感应区后重试")
    };
  }

  if (result?.finger_detected === false || result?.quality === "no_finger") {
    return {
      tone: "warn",
      title: "未检测到手指",
      summary: "没有检测到手指",
      detail: humanVitalsMessage(result, "请将指腹放入感应区")
    };
  }

  return {
    tone: "warn",
    title: "核心体征未读全",
    summary: missingCoreVitalsMessage(result),
    detail: humanVitalsMessage(result, "请保持姿势后重新测量")
  };
}

function hasReading(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0;
}

function hasCoreVitals(result) {
  return hasReading(result?.heart_rate) && hasReading(result?.spo2) && hasReading(result?.temperature);
}

function missingCoreVitalsMessage(result) {
  const missing = [];
  if (!hasReading(result?.heart_rate)) missing.push("心率");
  if (!hasReading(result?.spo2)) missing.push("血氧");
  if (!hasReading(result?.temperature)) missing.push("额温");
  return missing.length ? `${missing.join("、")}尚未读取，请保持姿势后重试` : "核心体征已读取";
}

function humanVitalsMessage(result, fallback) {
  const quality = String(result?.quality || "").toLowerCase();
  const message = String(result?.message || "").toLowerCase();
  if (quality === "no_finger" || message.includes("no finger")) {
    return "请将指腹贴合感应区后重试";
  }
  if (quality === "poor_signal" || message.includes("weak")) {
    return "请放松手指后重试";
  }
  if (quality === "error") {
    return "确认传感器与手指位置";
  }
  return fallback;
}
