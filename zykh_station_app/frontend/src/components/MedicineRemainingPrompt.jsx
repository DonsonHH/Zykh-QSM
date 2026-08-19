import React, { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, PackageCheck, PackageX } from "lucide-react";
import { describeMedicineCabinet } from "../utils/cabinetLightPresentation.js";

const INVENTORY_CONFIRM_SECONDS = 10;

export function MedicineRemainingPrompt({
  medicine,
  mode = "inventory",
  busy = false,
  message = "",
  error = "",
  confirmedState = "",
  cabinetLightOff = false,
  lightTurnsOffOnConfirm = false,
  onHasStock,
  onDepleted,
  onAcknowledge
}) {
  const [seconds, setSeconds] = useState(INVENTORY_CONFIRM_SECONDS);
  const cabinet = describeMedicineCabinet(medicine);
  const inventoryMode = mode === "inventory";
  const unknownMode = mode === "result_unknown";

  useEffect(() => {
    setSeconds(INVENTORY_CONFIRM_SECONDS);
  }, [medicine?.medicine_id, medicine?.record_id, mode]);

  useEffect(() => {
    if (!inventoryMode || busy || message || error) return undefined;
    const deadline = Date.now() + INVENTORY_CONFIRM_SECONDS * 1000;
    let lastValue = INVENTORY_CONFIRM_SECONDS;
    const timer = window.setInterval(() => {
      const nextValue = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      if (nextValue !== lastValue) {
        lastValue = nextValue;
        setSeconds(nextValue);
      }
      if (nextValue === 0) {
        window.clearInterval(timer);
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [busy, error, inventoryMode, message]);

  return (
    <div className="medicine-remaining-prompt" role={unknownMode ? "alert" : "status"} aria-live="polite">
      <span className={`remaining-prompt-icon ${unknownMode || confirmedState === "DEPLETED" || error ? "warning" : ""}`} aria-hidden="true">
        {unknownMode
          ? <AlertTriangle size={62} />
          : confirmedState === "DEPLETED" || error
            ? <PackageX size={62} />
            : inventoryMode ? <PackageCheck size={62} /> : <CheckCircle2 size={62} />}
      </span>
      <div className="remaining-prompt-copy">
        <p>{inventoryMode ? "库存确认" : unknownMode ? "现场安全确认" : "取药确认"}</p>
        <h3>{message || (inventoryMode
          ? "分类柜内还有药吗？"
          : unknownMode ? "亮灯结果待确认，请勿重复操作" : "请确认已取出药品")}</h3>
        <span>
          {message
            ? confirmedState === "DEPLETED"
              ? `${cabinet}已标记为缺药`
              : `${cabinet}库存已恢复`
            : `${medicine.name} · ${cabinet}`}
        </span>
        {!message && cabinetLightOff ? <small>分类柜指示灯已关闭，请核对取药后的实际库存。</small> : null}
        {!message && lightTurnsOffOnConfirm ? <small>取药完成后请选择实际库存，提交时会关闭分类柜指示灯。</small> : null}
        {!message && mode === "pickup" ? <small>请自行打开亮灯的分类柜取药，取好后关闭指示灯再继续。</small> : null}
        {!message && unknownMode ? <small>指示灯可能仍亮着；请现场确认后关灯，不要再次发起亮灯。</small> : null}
        {error ? <small role="alert">{error}</small> : null}
      </div>
      {!message ? (
        <>
          {inventoryMode ? (
            <div
              className={`remaining-prompt-progress${busy || seconds === 0 ? " paused" : ""}`}
              aria-label={seconds > 0 ? `${seconds}秒后请现场确认` : "请现场确认分类柜库存"}
            >
              <span />
              <strong>{seconds > 0 ? seconds : "请"}</strong>
              <small>{seconds > 0 ? "秒后请现场确认" : "现场确认"}</small>
            </div>
          ) : null}
          <div className="remaining-prompt-actions">
            {inventoryMode ? (
              <>
                <button type="button" className="remaining-depleted-action" onClick={onDepleted} disabled={busy}>
                  <PackageX size={22} aria-hidden="true" />
                  {busy ? "正在记录" : "已经用完"}
                </button>
                <button type="button" className="primary-action" onClick={onHasStock} disabled={busy}>
                  <PackageCheck size={22} aria-hidden="true" />
                  还有药
                </button>
              </>
            ) : (
              <button type="button" className="primary-action" onClick={onAcknowledge} disabled={busy}>
                <CheckCircle2 size={22} aria-hidden="true" />
                {busy ? "正在关闭指示灯" : unknownMode ? "关闭分类柜指示灯" : "我已取药，关闭指示灯"}
              </button>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
