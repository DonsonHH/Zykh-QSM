import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, BadgeCheck, Camera, PackagePlus, Pill, ScanLine } from "lucide-react";
import { loadQsmCapabilities, registerScannedMedicine, scanMedicine } from "../api/qsm.js";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";

const scanMode = "药品识别";

export function Scan({ notify, onNavigate }) {
  const [cameraStatus, setCameraStatus] = useState("checking");
  const [liveMessage, setLiveMessage] = useState("正在连接外设摄像头...");
  const [liveStatus, setLiveStatus] = useState("checking");
  const [result, setResult] = useState(null);
  const [registering, setRegistering] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const scanTimerRef = useRef(null);
  const lastCodeRef = useRef("");
  const matchingRef = useRef(false);

  useEffect(() => {
    let stopped = false;

    loadQsmCapabilities()
      .then((data) => {
        if (stopped) {
          return;
        }
        const available = data.camera === "available";
        setCameraStatus(available ? "available" : "unavailable");
        setLiveStatus(available ? "scanning" : "unavailable");
        setLiveMessage(available ? "请将条码放入取景框，系统每秒自动核验。" : "外设摄像头暂不可用。");
        if (available) {
          startScanLoop();
        }
      })
      .catch((error) => {
        setCameraStatus("unavailable");
        setLiveStatus("unavailable");
        setLiveMessage(error.message || "外设摄像头暂不可用。");
      });

    return () => {
      stopped = true;
      window.clearTimeout(scanTimerRef.current);
    };

    function startScanLoop() {
      window.clearTimeout(scanTimerRef.current);
      const tick = async () => {
        if (stopped) {
          return;
        }
        if (!matchingRef.current) {
          matchingRef.current = true;
          scanMedicine({ mode: scanMode })
            .then((data) => {
              if (!data.ok || !data.barcode) {
                setLiveStatus("scanning");
                setLiveMessage("正在识别：请让条码清晰、完整地出现在取景框中。");
                return;
              }
              if (data.barcode === lastCodeRef.current) {
                setLiveStatus("matched");
                setLiveMessage("已识别当前条码，请核对右侧药品信息。");
                return;
              }
              lastCodeRef.current = data.barcode;
              applyScanResult(data, data.barcode);
              setLiveStatus("matched");
              setLiveMessage("已匹配家庭药柜药品，请人工核验。");
            })
            .catch((error) => {
              setLiveStatus("preview");
              setLiveMessage(error.message || "实时扫码暂不可用，请稍后重试。");
            })
            .finally(() => {
              matchingRef.current = false;
            });
        }
        scanTimerRef.current = window.setTimeout(tick, 1000);
      };
      tick();
    }
  }, []);

  function applyScanResult(data, fallbackCode = "") {
    setCameraStatus(data.ok ? "available" : data.status || "available");
    if (data.ok === false) {
      setResult({
        barcode: data.barcode || fallbackCode || "--",
        name: "待人工核验",
        match_percent: 0,
        spec: "--",
        quantity: "--",
        expire_date: "--",
        slot: "--",
        source: data.source || "local"
      });
      notify(data.error_message || "条码未匹配，请人工核验");
      return false;
    }
    setResult(data);
    notify("识别结果已生成，请人工核验");
    return true;
  }


  function handleRegisterMedicine() {
    if (!result) {
      return;
    }
    const barcode = result.barcode && result.barcode !== "--" ? result.barcode : "";
    if (!barcode && !result.name) {
      notify("未识别到可录入信息，请调整药盒位置");
      return;
    }
    setRegistering(true);
    registerScannedMedicine({
      barcode,
      name: result.name || "待核验药品",
      spec: result.spec || "",
      expire_date: result.expire_date || "",
      stock: 1,
      unit: "盒",
      category: "扫码录入"
    })
      .then((data) => {
        if (!data.ok) {
          notify(data.message || "录入失败，请在药品页核对空仓");
          return;
        }
        setResult({
          ...result,
          medicine_id: data.medicine?.id || result.medicine_id,
          name: data.medicine?.name || result.name,
          slot: data.medicine?.hardware_slot || data.medicine?.slot || result.slot,
          quantity: data.medicine ? `${data.medicine.stock}${data.medicine.unit}` : result.quantity,
          expire_date: data.medicine?.expire_date || result.expire_date,
          match_percent: result.match_percent ?? (data.created ? 88 : 99)
        });
        notify(data.message || "已录入药柜");
        if (data.medicine?.id && onNavigate) {
          window.setTimeout(() => onNavigate("medicines", { medicineId: data.medicine.id }), 480);
        }
      })
      .catch((error) => notify(error.message || "录入失败"))
      .finally(() => setRegistering(false));
  }

  return (
    <main className="scan-page" id="main-content">
      <section className="scan-capture-panel">
        <div className="scan-heading">
          <button className="icon-action" type="button" onClick={() => onNavigate("home")} aria-label="返回首页">
            <ArrowLeft size={24} aria-hidden="true" />
          </button>
          <h2 className="page-entry-cue">扫码核验</h2>
        </div>

        <div className={`camera-stage live ${cameraStatus === "unavailable" ? "unavailable" : ""}`}>
          {cameraStatus === "unavailable" ? (
            <>
              <ScanLine size={54} aria-hidden="true" />
              <strong>摄像头暂不可用</strong>
            </>
          ) : (
            <>
              <img
                key={previewKey}
                className="camera-preview"
                src={`/api/camera/stream?session=${previewKey}`}
                alt="外设摄像头实时预览"
                onLoad={() => {
                  setCameraStatus("available");
                  setLiveStatus("scanning");
                  setLiveMessage("请将条码放入取景框，系统每秒自动核验。");
                }}
                onError={() => {
                  setLiveStatus("preview");
                  setLiveMessage("视频流正在恢复，请稍候。");
                  window.setTimeout(() => setPreviewKey((value) => value + 1), 1400);
                }}
              />
              <div className="scan-frame" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
              </div>
            </>
          )}
        </div>
        <div className={`scan-live-status-row ${liveStatus}`} aria-live="polite">
          {liveStatus === "matched" ? <BadgeCheck size={20} aria-hidden="true" /> : <Camera size={20} aria-hidden="true" />}
          <strong>{liveStatus === "matched" ? "已识别" : liveStatus === "scanning" ? "自动识别" : "摄像头预览"}</strong>
          <span>{liveMessage || "请检查外设摄像头连接后重试。"}</span>
        </div>
      </section>

      <section className="scan-result-panel">
        <div className="scan-result-heading">
          <span aria-hidden="true">
            <BadgeCheck size={34} />
          </span>
          <h2>{result ? result.name : "识别结果"}</h2>
        </div>

        {result ? (
          <>
            <div className="match-card">
              <Pill size={28} aria-hidden="true" />
              <span>匹配度</span>
              <strong>{result.match_percent ?? 0}%</strong>
            </div>
            <div className="scan-meta-grid">
              <article className="scan-meta-wide">
                <span>条码</span>
                <strong>{result.barcode || "--"}</strong>
              </article>
              <article className="scan-meta-wide">
                <span>规格</span>
                <strong>{result.spec || "--"}</strong>
              </article>
              <article>
                <span>数量</span>
                <strong>{result.quantity || "--"}</strong>
              </article>
              <article>
                <span>仓位</span>
                <strong>{result.slot || "--"}</strong>
              </article>
            </div>
          </>
        ) : (
          <div className="scan-empty-state">
            <StrokeDrawIcon
              icon={ScanLine}
              size={54}
              strokeWidth={1.8}
              mode="yoyo"
              active={cameraStatus !== "unavailable" && liveStatus !== "matched"}
            />
            <strong>暂无识别结果</strong>
            <p>请将药盒条码对准取景框，系统会连续自动核验。</p>
          </div>
        )}

        <div className="scan-result-actions">
          <button
            className="primary-action"
            type="button"
            disabled={!result || registering}
            onClick={handleRegisterMedicine}
          >
            <PackagePlus size={24} aria-hidden="true" />
            <span>{registering ? "录入中..." : "完成核验并录入"}</span>
          </button>
        </div>
      </section>
    </main>
  );
}
