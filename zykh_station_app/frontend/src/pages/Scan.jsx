import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, BadgeCheck, Camera, CheckCircle2, Keyboard, Pill, RotateCcw, ScanLine } from "lucide-react";
import { loadQsmCapabilities, scanMedicine, scanMedicineFrame } from "../api/qsm.js";

const scanMode = "药品识别";

export function Scan({ notify, onNavigate }) {
  const [cameraStatus, setCameraStatus] = useState("checking");
  const [liveMessage, setLiveMessage] = useState("正在打开本机摄像头...");
  const [liveStatus, setLiveStatus] = useState("checking");
  const [result, setResult] = useState(null);
  const [capturing, setCapturing] = useState(false);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const detectorRef = useRef(null);
  const serverScanRef = useRef(false);
  const scanTimerRef = useRef(null);
  const lastCodeRef = useRef("");
  const matchingRef = useRef(false);

  useEffect(() => {
    let stopped = false;

    loadQsmCapabilities()
      .then((data) => setCameraStatus(data.camera || "unavailable"))
      .catch(() => setCameraStatus("unavailable"));

    startPreview();

    return () => {
      stopped = true;
      stopPreview();
    };

    async function startPreview() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCameraStatus("unavailable");
        setLiveStatus("unavailable");
        setLiveMessage("当前浏览器无法打开摄像头，可使用拍照识别或手动输入。");
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 1280 },
            height: { ideal: 720 },
            facingMode: "environment"
          },
          audio: false
        });
        if (stopped) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setCameraStatus("available");
        setupDetector();
        startScanLoop();
      } catch (error) {
        setCameraStatus("unavailable");
        setLiveStatus("unavailable");
        setLiveMessage(error?.message || "摄像头暂不可用，可手动输入条码完成核验。");
      }
    }

    function setupDetector() {
      if (!("BarcodeDetector" in window)) {
        detectorRef.current = null;
        serverScanRef.current = true;
        setLiveStatus("scanning");
        setLiveMessage("实时扫码中：本机后端正在识别摄像头画面。");
        return;
      }
      try {
        detectorRef.current = new window.BarcodeDetector({
          formats: ["qr_code", "ean_13", "ean_8", "code_128", "code_39", "upc_a", "upc_e", "data_matrix"]
        });
      } catch {
        detectorRef.current = new window.BarcodeDetector();
      }
      serverScanRef.current = false;
      setLiveStatus("scanning");
      setLiveMessage("请将条码或二维码放入取景框，系统会自动识别。");
    }

    function startScanLoop() {
      window.clearTimeout(scanTimerRef.current);
      const tick = async () => {
        if (stopped) {
          return;
        }
        const detector = detectorRef.current;
        const video = videoRef.current;
        if (detector && video?.readyState >= 2 && !matchingRef.current) {
          try {
            const codes = await detector.detect(video);
            const firstCode = codes?.[0]?.rawValue?.trim();
            if (firstCode) {
              handleLiveCode(firstCode);
            }
          } catch {
            setLiveStatus("preview");
            setLiveMessage("实时扫码暂不可用，请使用拍照识别。");
            detectorRef.current = null;
            serverScanRef.current = true;
          }
        }
        if (!detector && serverScanRef.current && video?.readyState >= 2 && !matchingRef.current) {
          scanCurrentFrame();
        }
        scanTimerRef.current = window.setTimeout(tick, serverScanRef.current ? 1100 : 650);
      };
      tick();
    }

    function stopPreview() {
      window.clearTimeout(scanTimerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      detectorRef.current = null;
      serverScanRef.current = false;
    }
  }, []);

  function handleLiveCode(rawCode) {
    const code = rawCode.trim();
    if (!code || code === lastCodeRef.current) {
      return;
    }
    lastCodeRef.current = code;
    matchingRef.current = true;
    setLiveStatus("matched");
    setLiveMessage(`识别到 ${code}，正在匹配家庭药柜药品。`);
    scanMedicine({ manual_code: code, mode: scanMode })
      .then((data) => {
        applyScanResult(data, code);
        setLiveMessage(data.ok ? "已匹配家庭药柜药品，请人工核验。" : "条码未匹配，请人工核验或重扫。");
      })
      .catch((error) => {
        setResult({ barcode: code, name: "待人工核验", match_percent: 0, spec: "--", quantity: "--", expire_date: "--", slot: "--" });
        setLiveMessage(error.message || "条码匹配失败，请人工核验。");
      })
      .finally(() => {
        window.setTimeout(() => {
          matchingRef.current = false;
        }, 1400);
      });
  }

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

  function capturePreviewFrame(targetWidth = 720, quality = 0.78) {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.videoWidth === 0 || video.videoHeight === 0) {
      return null;
    }
    const targetHeight = Math.round((video.videoHeight / video.videoWidth) * targetWidth) || 480;
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) {
      return null;
    }
    context.drawImage(video, 0, 0, targetWidth, targetHeight);
    return canvas.toDataURL("image/jpeg", quality);
  }

  function scanCurrentFrame() {
    const imageData = capturePreviewFrame(640, 0.74);
    if (!imageData) {
      return;
    }
    matchingRef.current = true;
    scanMedicineFrame({ image_data: imageData, mode: scanMode })
      .then((data) => {
        if (data.ok) {
          if (data.barcode && data.barcode === lastCodeRef.current) {
            setLiveStatus("matched");
            setLiveMessage("已识别当前条码，请人工核验。");
            return;
          }
          if (data.barcode) {
            lastCodeRef.current = data.barcode;
          }
          applyScanResult(data);
          setLiveStatus("matched");
          setLiveMessage("已匹配家庭药柜药品，请人工核验。");
          return;
        }
        setLiveStatus("scanning");
        setLiveMessage("实时扫码中：请将条码或二维码对准取景框。");
      })
      .catch(() => {
        setLiveStatus("preview");
        setLiveMessage("实时扫码暂不可用，请使用拍照识别。");
        serverScanRef.current = false;
      })
      .finally(() => {
        window.setTimeout(() => {
          matchingRef.current = false;
        }, 450);
      });
  }

  function handleCapture() {
    const imageData = capturePreviewFrame(960, 0.82);
    if (!imageData) {
      notify("摄像头预览未就绪，请稍候或手动输入条码");
      return;
    }
    setCapturing(true);
    scanMedicineFrame({ image_data: imageData, mode: scanMode })
      .then((data) => {
        applyScanResult(data);
      })
      .catch(() => {
        setResult(null);
        notify("当前画面未完成识别，可手动输入条码完成核验");
      })
      .finally(() => setCapturing(false));
  }

  function handleManualInput() {
    const manualCode = window.prompt("请输入药品条码");
    if (!manualCode) {
      return;
    }
    scanMedicine({ manual_code: manualCode.trim(), mode: scanMode })
      .then((data) => {
        applyScanResult(data, manualCode.trim());
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

        <div className={`camera-stage live ${cameraStatus === "unavailable" ? "unavailable" : ""}`}>
          {cameraStatus === "unavailable" ? (
            <>
              <span aria-hidden="true">
                <ScanLine size={54} />
              </span>
              <strong>摄像头暂不可用</strong>
              <p>{liveMessage || "可手动输入条码，或从记录中完成核验。"}</p>
            </>
          ) : (
            <>
              <video ref={videoRef} className="camera-preview" muted playsInline autoPlay aria-label="本机摄像头实时预览" />
              <canvas ref={canvasRef} className="scan-frame-buffer" aria-hidden="true" />
              <div className="scan-frame" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
              </div>
              <div className={`live-scan-badge ${liveStatus}`}>
                <Camera size={18} aria-hidden="true" />
                <strong>{liveStatus === "matched" ? "已识别" : liveStatus === "scanning" ? "实时扫码中" : "摄像头预览"}</strong>
                <span>{liveMessage}</span>
              </div>
            </>
          )}
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
              lastCodeRef.current = "";
              matchingRef.current = false;
              setLiveStatus(detectorRef.current || serverScanRef.current ? "scanning" : "preview");
              setLiveMessage(
                detectorRef.current || serverScanRef.current
                  ? "请将条码或二维码放入取景框，系统会自动识别。"
                  : "请调整药盒位置后拍照识别。"
              );
            }}
          >
            <RotateCcw size={22} aria-hidden="true" />
            <span>重新扫码</span>
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
