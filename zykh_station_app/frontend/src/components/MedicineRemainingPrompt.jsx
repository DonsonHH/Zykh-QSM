import React, { useEffect, useRef, useState } from "react";
import { PackageCheck, PackageX } from "lucide-react";

const INVENTORY_CONFIRM_SECONDS = 10;

export function MedicineRemainingPrompt({ medicine, busy = false, message = "", onHasStock, onDepleted }) {
  const [seconds, setSeconds] = useState(INVENTORY_CONFIRM_SECONDS);
  const onHasStockRef = useRef(onHasStock);

  useEffect(() => {
    onHasStockRef.current = onHasStock;
  }, [onHasStock]);

  useEffect(() => {
    if (busy || message) return undefined;
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
        onHasStockRef.current();
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [busy, message]);

  return (
    <div className="medicine-remaining-prompt" role="status" aria-live="polite">
      <span className={`remaining-prompt-icon ${message ? "warning" : ""}`} aria-hidden="true">
        {message ? <PackageX size={62} /> : <PackageCheck size={62} />}
      </span>
      <div className="remaining-prompt-copy">
        <p>库存确认</p>
        <h3>{message || "药柜内还有药吗？"}</h3>
        <span>
          {message
            ? `${medicine.hardware_slot || medicine.slot} 号仓已标记为缺药`
            : `${medicine.name} · ${medicine.hardware_slot || medicine.slot} 号仓`}
        </span>
      </div>
      {!message ? (
        <>
          <div className={`remaining-prompt-progress${busy ? " paused" : ""}`} aria-label={`${seconds}秒后默认还有药`}>
            <span />
            <strong>{seconds}</strong>
            <small>秒后默认还有药</small>
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
