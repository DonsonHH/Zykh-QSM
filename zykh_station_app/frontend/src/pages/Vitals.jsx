import React, { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowLeft, HeartPulse, ScanFace, Thermometer } from "lucide-react";
import { loadQsmVitals } from "../api/qsm.js";

const measurementSeconds = 15;
const initialSteps = [
  { id: "head", label: "额头对准屏幕上方", state: "idle" },
  { id: "finger", label: "手指保持稳定", state: "idle" },
  { id: "read", label: "读取体温、心率和血氧", state: "idle" }
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
            <p>体征测量</p>
            <h2>请按提示完成额温、心率和血氧测量</h2>
          </div>
        </div>

        <div className="vitals-guide-grid">
          <article className="vitals-guide-card face">
            <span aria-hidden="true">
              <ScanFace size={48} />
            </span>
            <div>
              <h3>额温测量</h3>
              <strong>头部距离屏幕约 20cm</strong>
              <p>请让额头对准屏幕上方的额温模块，保持 2-3 秒。</p>
            </div>
          </article>

          <article className="vitals-guide-card finger">
            <span aria-hidden="true">
              <HeartPulse size={48} />
            </span>
            <div>
              <h3>心率血氧</h3>
              <strong>手指放在屏幕右前方示意处</strong>
              <p>指腹覆盖传感器并保持稳定，测量约 10-15 秒。</p>
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
            <strong>{phase === "measuring" ? "请保持当前姿势" : result ? "可重新测量" : "准备好后开始"}</strong>
            <p>
              {phase === "measuring"
                ? countdown > 0
                  ? "额头和手指都不要移动，系统正在读取传感器信号。"
                  : "正在等待外设返回稳定读数，请继续保持姿势。"
                : result
                  ? "如手指信号不稳定，请按提示重新放置后再测。"
                  : "测量开始后会自动倒计时，并同步读取额温、心率和血氧。"}
            </p>
          </div>
        </section>

        <div className="vitals-progress" aria-label="测量进度">
          {steps.map((step) => (
            <article key={step.id} className={step.state}>
              <span />
              <strong>{step.label}</strong>
            </article>
          ))}
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
            <p>测量结果</p>
            <h2>{status.title}</h2>
          </div>
        </div>

        <div className="vitals-metric-grid">
          <Metric icon={Thermometer} label="额温" value={formatMetric(result?.temperature, "℃", 1)} />
          <Metric icon={HeartPulse} label="心率" value={formatMetric(result?.heart_rate, "次/分")} />
          <Metric icon={Activity} label="血氧" value={formatMetric(result?.spo2, "%")} />
        </div>

        <div className="vitals-status-card">
          <strong>{status.summary}</strong>
          <p>{status.detail}</p>
        </div>
      </section>
    </main>
  );
}

function Metric({ icon: Icon, label, value }) {
  return (
    <article className="vitals-metric">
      <Icon size={26} aria-hidden="true" />
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function formatMetric(value, unit, fractionDigits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "待测";
  }
  const numeric = Number(value);
  return `${numeric.toFixed(fractionDigits)}${unit}`;
}

function describeVitals(result, errorMessage, phase, countdown) {
  if (phase === "measuring") {
    return {
      tone: "active",
      title: "测量中",
      summary: "正在读取体征信号",
      detail:
        countdown > 0
          ? `请保持额头对准和手指稳定，剩余约 ${countdown} 秒。`
          : "正在等待外设返回稳定读数，请继续保持姿势。"
    };
  }

  if (!result && !errorMessage) {
    return {
      tone: "idle",
      title: "等待测量",
      summary: "请先完成姿势准备",
      detail: "额头对准屏幕上方，手指放在右前方传感器区域，再点击开始测量。"
    };
  }

  if (errorMessage || result?.ok === false || result?.status === "unavailable") {
    return {
      tone: "warn",
      title: "设备暂不可用",
      summary: "本次测量未完成",
      detail: errorMessage || result?.error_message || "外设返回不可用状态，请检查连接后重试。"
    };
  }

  if (result?.quality === "error") {
    return {
      tone: "warn",
      title: "心率血氧模块异常",
      summary: "本次未形成心率和血氧读数",
      detail: humanVitalsMessage(result, "模块返回异常状态，请确认手指传感器连接后重新测量。")
    };
  }

  if (result?.finger_detected === false || result?.quality === "no_finger") {
    return {
      tone: "warn",
      title: "未检测到手指",
      summary: "心率和血氧没有形成稳定读数",
      detail: humanVitalsMessage(result, "请将指腹完整覆盖屏幕右前方传感器，保持稳定后重新测量。")
    };
  }

  if (result?.partial) {
    return {
      tone: "warn",
      title: "只读到部分体征",
      summary: "本次只完成额温读取",
      detail: humanVitalsMessage(result, "心率血氧模块未返回完整数据，请按引导放置手指后重新测量。")
    };
  }

  if (result?.quality === "poor_signal" || result?.heart_rate == null || result?.spo2 == null) {
    return {
      tone: "warn",
      title: "信号偏弱",
      summary: "心率或血氧本次未形成稳定读数",
      detail: humanVitalsMessage(result, "请放松手指并保持不动，重新测量 10-15 秒。")
    };
  }

  return {
    tone: "good",
    title: "测量完成",
    summary: "体温、心率和血氧已记录",
    detail: "可返回首页或问询流程继续后续操作。"
  };
}

function humanVitalsMessage(result, fallback) {
  const quality = String(result?.quality || "").toLowerCase();
  const message = String(result?.message || "").toLowerCase();
  if (quality === "no_finger" || message.includes("no finger")) {
    return "未检测到稳定手指信号，请将指腹完整覆盖传感器后重新测量。";
  }
  if (quality === "poor_signal" || message.includes("weak")) {
    return "手指信号偏弱，请保持手指稳定后重新测量 10-15 秒。";
  }
  if (quality === "error") {
    return "心率血氧模块返回异常状态，请确认传感器连接和手指位置后重新测量。";
  }
  return fallback;
}
