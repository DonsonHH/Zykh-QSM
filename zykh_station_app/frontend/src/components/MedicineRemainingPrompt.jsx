import React, { useEffect, useState } from "react";
import { PackageCheck, PackageX } from "lucide-react";

const INVENTORY_CONFIRM_SECONDS = 10;

export function MedicineRemainingPrompt({ medicine, busy = false, message = "", error = "", confirmedState = "", onHasStock, onDepleted }) {
  const [seconds, setSeconds] = useState(INVENTORY_CONFIRM_SECONDS);

  useEffect(() => {
    if (busy || message || error) return undefined;
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
  }, [busy, error, message]);

  return (
    <div className="medicine-remaining-prompt" role="status" aria-live="polite">
      <span className={`remaining-prompt-icon ${confirmedState === "DEPLETED" || error ? "warning" : ""}`} aria-hidden="true">
        {confirmedState === "DEPLETED" || error ? <PackageX size={62} /> : <PackageCheck size={62} />}
      </span>
      <div className="remaining-prompt-copy">
        <p>库存确认</p>
        <h3>{message || "药柜内还有药吗？"}</h3>
        <span>
          {message
            ? confirmedState === "DEPLETED"
              ? `${medicine.hardware_slot || medicine.slot} 号仓已标记为缺药`
              : `${medicine.hardware_slot || medicine.slot} 号仓库存已恢复`
            : `${medicine.name} · ${medicine.hardware_slot || medicine.slot} 号仓`}
        </span>
        {error ? <small role="alert">{error}</small> : null}
      </div>
      {!message ? (
        <>
          <div
            className={`remaining-prompt-progress${busy || seconds === 0 ? " paused" : ""}`}
            aria-label={seconds > 0 ? `${seconds}秒后请现场确认` : "请现场确认药柜库存"}
          >
            <span />
            <strong>{seconds > 0 ? seconds : "请"}</strong>
            <small>{seconds > 0 ? "秒后请现场确认" : "现场确认"}</small>
          </div>
          <div className="remaining-prompt-actions">
            <button type="button" className="remaining-depleted-action" onClick={onDepleted} disabled={busy}>
              <PackageX size={22} aria-hidden="true" />
              {busy ? "正在记录" : "已经用完"}
            </button>
            <button type="button" className="primary-action" onClick={onHasStock} disabled={busy}>
              <PackageCheck size={22} aria-hidden="true" />
              还有药
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
