import React, { useEffect, useState } from "react";
import { ArrowLeft, BadgeCheck, Camera, CheckCircle2, Keyboard, Pill, RotateCcw, ScanLine } from "lucide-react";
import { loadQsmCapabilities, scanMedicine } from "../api/qsm.js";

const scanModes = ["药品识别", "站点码", "取药确认"];

export function Scan({ notify, onNavigate }) {
  const [activeMode, setActiveMode] = useState(scanModes[0]);
  const [cameraStatus, setCameraStatus] = useState("checking");
  const [result, setResult] = useState(null);
  const [capturing, setCapturing] = useState(false);

  useEffect(() => {
    loadQsmCapabilities()
      .then((data) => setCameraStatus(data.camera || "unavailable"))
      .catch(() => setCameraStatus("unavailable"));
  }, []);

  function handleCapture() {
    setCapturing(true);
    scanMedicine({ mode: activeMode })
      .then((data) => {
        setCameraStatus(data.ok ? "available" : data.status || "unavailable");
        if (data.ok === false) {
          setResult(null);
          notify(data.error_message || "未识别到药品信息，请人工核验");
          return;
        }
        setResult(data);
        notify("识别结果已生成，请人工核验");
      })
      .catch(() => {
        setCameraStatus("unavailable");
        setResult(null);
        notify("摄像头暂不可用，可手动输入条码完成核验");
      })
      .finally(() => setCapturing(false));
  }

  function handleManualInput() {
    const manualCode = window.prompt("请输入药品条码");
    if (!manualCode) {
      return;
    }
    scanMedicine({ manual_code: manualCode.trim(), mode: activeMode })
      .then((data) => {
        if (data.ok === false) {
          setResult({ barcode: manualCode.trim(), name: "待人工核验", match_percent: 0, spec: "--", quantity: "--", expire_date: "--", slot: "--" });
          notify(data.error_message || "条码未匹配，请人工核验");
          return;
        }
        setResult(data);
        notify("条码已匹配，请人工核验");
      })
      .catch((error) => notify(error.message || "手动核验失败"));
  }

  return (
    <main className="scan-page" id="main-content">
      <section className="scan-capture-panel">
        <div className="scan-heading">
          <button className="icon-action" type="button" onClick={() => onNavigate("home")} aria-label="返回首页">
            <ArrowLeft size={24} aria-hidden="true" />
          </button>
          <div>
            <p>扫码识别</p>
            <h2>拍照 / 条码核验</h2>
          </div>
        </div>

        <div className="scan-mode-row" aria-label="识别模式">
          {scanModes.map((mode) => (
            <button
              key={mode}
              type="button"
              className={mode === activeMode ? "active" : ""}
              onClick={() => setActiveMode(mode)}
            >
              {mode}
            </button>
          ))}
        </div>

        <div className={`camera-stage ${cameraStatus === "unavailable" ? "unavailable" : ""}`}>
          <span aria-hidden="true">
            {cameraStatus === "unavailable" ? <ScanLine size={54} /> : <Camera size={58} />}
          </span>
          <strong>
            {cameraStatus === "checking"
              ? "正在检查摄像头"
              : cameraStatus === "unavailable"
                ? "摄像头暂不可用"
                : "摄像头入口已就绪"}
          </strong>
          <p>
            {cameraStatus === "checking"
              ? "请稍候，正在读取本机摄像头状态。"
              : cameraStatus === "unavailable"
                ? "可手动输入条码，或从记录中完成核验。"
                : `当前模式：${activeMode}，拍照后请人工确认识别结果。`}
          </p>
        </div>

        <div className="scan-action-row">
          <button className="primary-action" type="button" onClick={handleCapture} disabled={capturing}>
            <Camera size={24} aria-hidden="true" />
            <span>{capturing ? "识别中..." : "拍照识别"}</span>
          </button>
          <button className="secondary-action compact" type="button" onClick={handleManualInput}>
            <Keyboard size={22} aria-hidden="true" />
            <span>手动输入</span>
          </button>
          <button
            className="secondary-action compact"
            type="button"
            onClick={() => {
              setResult(null);
              handleCapture();
            }}
          >
            <RotateCcw size={22} aria-hidden="true" />
            <span>重新识别</span>
          </button>
        </div>
      </section>

      <section className="scan-result-panel">
        <div className="scan-result-heading">
          <span aria-hidden="true">
            <BadgeCheck size={34} />
          </span>
          <div>
            <p>识别结果</p>
            <h2>{result ? result.name : "等待核验"}</h2>
          </div>
        </div>

        {result ? (
          <>
            <div className="match-card">
              <Pill size={28} aria-hidden="true" />
              <span>匹配度</span>
              <strong>{result.match_percent ?? 0}%</strong>
            </div>
            <div className="scan-meta-grid">
              <article>
                <span>条码</span>
                <strong>{result.barcode || "--"}</strong>
              </article>
              <article>
                <span>规格</span>
                <strong>{result.spec || "--"}</strong>
              </article>
              <article>
                <span>数量</span>
                <strong>{result.quantity || "--"}</strong>
              </article>
              <article>
                <span>有效期</span>
                <strong>{result.expire_date || "--"}</strong>
              </article>
              <article>
                <span>仓位</span>
                <strong>{result.slot || "--"}</strong>
              </article>
            </div>
          </>
        ) : (
          <div className="scan-empty-state">
            <ScanLine size={44} aria-hidden="true" />
            <strong>暂无识别结果</strong>
            <p>请拍照识别，或使用手动输入完成条码核验。</p>
          </div>
        )}

        <div className="scan-result-actions">
          <button
            className="primary-action"
            type="button"
            disabled={!result}
            onClick={() => notify("核验完成，已保留本地记录")}
          >
            <CheckCircle2 size={24} aria-hidden="true" />
            <span>完成核验</span>
          </button>
          <button className="secondary-action compact" type="button" onClick={() => onNavigate("medicines")}>
            查看药品
          </button>
        </div>
      </section>
    </main>
  );
}
