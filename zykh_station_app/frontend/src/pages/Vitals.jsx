import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Check,
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

const measurementSeconds = 18;
const initialSteps = [
  { id: "prepare", label: "对准", icon: ScanFace, state: "idle" },
  { id: "signal", label: "覆盖", icon: Fingerprint, state: "idle" },
  { id: "reference", label: "保持", icon: ShieldCheck, state: "idle" }
];

export function Vitals({ notify, onNavigate, returnPage = "home" }) {
  const [phase, setPhase] = useState("idle");
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [countdown, setCountdown] = useState(measurementSeconds);
  const requestIdRef = useRef(0);

  const returnLabel = returnPage === "inquiry" ? "返回问询" : "返回首页";
  const status = useMemo(() => describeVitals(result, errorMessage, phase, countdown), [countdown, errorMessage, phase, result]);
  const elapsedSeconds = measurementSeconds - countdown;
  const progressPercent =
    phase === "done" ? 100 : phase === "measuring" ? Math.min(100, Math.round((elapsedSeconds / measurementSeconds) * 100)) : 0;
  const steps = useMemo(
    () =>
      initialSteps.map((step, index) => ({
        ...step,
        state:
          phase === "done"
            ? "done"
            : phase !== "measuring"
              ? "idle"
              : index === 0
                ? elapsedSeconds < 3
                  ? "running"
                  : "done"
                : index === 1
                  ? elapsedSeconds < 12
                    ? "active"
                    : "done"
                  : elapsedSeconds < 12
                    ? "idle"
                    : "running"
      })),
    [elapsedSeconds, phase]
  );

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
        if (data.quality === "error") {
          notify(data.message || "心率血氧模块读取异常，请重新测量");
          return;
        }
        if (data.finger_detected === false || data.quality === "no_finger" || data.quality === "poor_signal") {
          notify("未检测到稳定手指信号，请按引导重新放置后重测");
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
            <h2>准备测量</h2>
          </div>
        </div>

        <div className={`vitals-visual-guide ${phase}`}>
          <article className="vitals-pose-card forehead">
            <div className="vitals-pose-graphic" aria-hidden="true">
              <span className="vitals-sensor-cap" />
              <ScanFace size={76} />
              <span className="vitals-distance-mark">
                <MoveVertical size={22} />
                20cm
              </span>
            </div>
            <div className="vitals-pose-label">
              <span>额头</span>
              <strong>对准屏幕上方</strong>
            </div>
          </article>

          <article className="vitals-pose-card fingertip">
            <div className="vitals-pose-graphic" aria-hidden="true">
              <span className="vitals-finger-target" />
              <Fingerprint size={78} />
              <span className="vitals-hold-mark">保持</span>
            </div>
            <div className="vitals-pose-label">
              <span>手指</span>
              <strong>指腹完整覆盖</strong>
            </div>
          </article>
        </div>

        <section className={`vitals-measure-console ${phase}`} aria-label="测量倒计时">
          <div className="vitals-ring" style={{ "--progress": `${progressPercent}%` }}>
            <div>
              <strong>{phase === "measuring" ? countdown : result ? "完成" : "准备"}</strong>
              <span>{phase === "measuring" ? "秒" : "测量"}</span>
            </div>
          </div>
          <div className="vitals-console-copy">
            <strong>{measurementTitle(phase, result)}</strong>
            <p>{measurementCue(phase, countdown, result)}</p>
          </div>
          <span className="vitals-signal-wave" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
        </section>

        <div className="vitals-progress" aria-label="测量进度">
          {steps.map((step) => {
            const StepIcon = step.state === "done" ? Check : step.icon;
            return (
              <article key={step.id} className={step.state}>
                <span>
                  <StepIcon size={20} aria-hidden="true" />
                </span>
              <strong>{step.label}</strong>
              </article>
            );
          })}
        </div>

        <div className="vitals-action-row">
          <button className="primary-action" type="button" onClick={handleMeasure} disabled={phase === "measuring"}>
            <Activity size={24} aria-hidden="true" />
            <span>{phase === "measuring" ? "正在测量..." : result ? "重新测量" : "开始测量"}</span>
          </button>
          <button className="secondary-action compact" type="button" onClick={handleBack}>
            {returnLabel}
          </button>
        </div>
      </section>

      <section className={`vitals-result-panel ${status.tone}`} aria-label="体征测量结果">
        <div className="vitals-result-heading">
          <span aria-hidden="true">
            <Thermometer size={34} />
          </span>
          <div>
            <p>实时结果</p>
            <h2 aria-live="polite">{status.title}</h2>
          </div>
        </div>

        <div className="vitals-metric-grid">
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
          <Metric
            icon={Fingerprint}
            label="指温参考"
            value={formatMetric(result?.body_temperature, "℃", phase, result, 2)}
            tone="finger"
          />
        </div>

        <div className="vitals-reference-grid" aria-label="辅助体征参考">
          <ReferenceMetric icon={Gauge} label="血压" value={formatPressure(result, phase)} />
          <ReferenceMetric
            icon={Wind}
            label="呼吸"
            value={formatReference(result?.respiratory_rate, "次/分", phase, result)}
          />
          <ReferenceMetric icon={Waves} label="HRV" value={formatReference(result?.hrv_sdnn, "ms", phase, result)} />
        </div>

        <div className="vitals-status-card">
          <span aria-hidden="true">
            <ShieldCheck size={24} />
          </span>
          <div>
            <strong>{status.summary}</strong>
            <p>{status.detail}</p>
          </div>
        </div>
      </section>
    </main>
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
    return "···";
  }
  if (!result) {
    return "--";
  }
  if (value === null || value === undefined || Number.isNaN(Number(value)) || Number(value) <= 0) {
    return "未读取";
  }
  const numeric = Number(value);
  return `${numeric.toFixed(fractionDigits)}${unit}`;
}

function formatPressure(result, phase) {
  if (phase === "measuring") {
    return "···";
  }
  const systolic = Number(result?.systolic_pressure);
  const diastolic = Number(result?.diastolic_pressure);
  if (!Number.isFinite(systolic) || !Number.isFinite(diastolic) || systolic <= 0 || diastolic <= 0) {
    return result ? "未生成" : "--";
  }
  return `${Math.round(systolic)}/${Math.round(diastolic)}`;
}

function formatReference(value, unit, phase, result) {
  if (phase === "measuring") {
    return "···";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return result ? "未生成" : "--";
  }
  return `${Math.round(numeric)}${unit}`;
}

function describeVitals(result, errorMessage, phase, countdown) {
  if (phase === "measuring") {
    return {
      tone: "active",
      title: "测量中",
      summary: "保持不动",
      detail: "正在形成稳定读数"
    };
  }

  if (!result && !errorMessage) {
    return {
      tone: "idle",
      title: "等待测量",
      summary: "对准 · 覆盖 · 保持",
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

  if (result?.quality === "error") {
    return {
      tone: "warn",
      title: "心率血氧模块异常",
      summary: "请重新放置手指",
      detail: humanVitalsMessage(result, "确认指腹覆盖后重试")
    };
  }

  if (result?.finger_detected === false || result?.quality === "no_finger") {
    return {
      tone: "warn",
      title: "未检测到手指",
      summary: "没有检测到手指",
      detail: humanVitalsMessage(result, "请让指腹完整覆盖传感器")
    };
  }

  if (result?.partial) {
    return {
      tone: "warn",
      title: "只读到部分体征",
      summary: "只完成部分测量",
      detail: humanVitalsMessage(result, "重新覆盖手指后测量")
    };
  }

  if (result?.quality === "poor_signal" || result?.heart_rate == null || result?.spo2 == null) {
    return {
      tone: "warn",
      title: "信号偏弱",
      summary: "信号尚未稳定",
      detail: humanVitalsMessage(result, "放松手指并保持不动")
    };
  }

  return {
    tone: "good",
    title: "测量完成",
    summary: result?.reference_ready ? "全部数据已记录" : "心率、血氧已记录",
    detail: result?.reference_ready ? "辅助参考已生成" : "血压与 HRV 可再次测量"
  };
}

function humanVitalsMessage(result, fallback) {
  const quality = String(result?.quality || "").toLowerCase();
  const message = String(result?.message || "").toLowerCase();
  if (quality === "no_finger" || message.includes("no finger")) {
    return "指腹完整覆盖后重试";
  }
  if (quality === "poor_signal" || message.includes("weak")) {
    return "保持手指稳定后重试";
  }
  if (quality === "error") {
    return "确认传感器与手指位置";
  }
  return fallback;
}

function measurementTitle(phase, result) {
  if (phase === "measuring") {
    return "保持不动";
  }
  return result ? "测量结束" : "准备就绪";
}

function measurementCue(phase, countdown, result) {
  if (phase === "measuring") {
    return countdown > 0 ? "额头对准 · 指腹覆盖" : "正在生成结果";
  }
  return result ? "可重新测量" : "点击下方按钮开始";
}
