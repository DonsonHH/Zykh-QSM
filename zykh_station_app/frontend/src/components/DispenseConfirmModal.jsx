import React, { useEffect, useState } from "react";
import { Minus, Plus, ShieldCheck, X } from "lucide-react";

export function DispenseConfirmModal({ medicine, open, submitting, result, error, onCancel, onSubmit }) {
  const [quantity, setQuantity] = useState(1);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (open) {
      setQuantity(1);
      setChecked(false);
    }
  }, [medicine?.id, open]);

  if (!open || !medicine) {
    return null;
  }

  function changeQuantity(nextQuantity) {
    setQuantity(Math.max(1, Math.min(medicine.stock, nextQuantity)));
  }

  function handleSubmit() {
    onSubmit({
      medicine_id: medicine.id,
      slot: medicine.slot,
      quantity,
      reason: "站点药品页取药确认",
      confirmed_safety_notice: checked,
      confirm_real_dispense: checked
    });
  }

  return (
    <div className="modal-layer" role="presentation">
      <section className="dispense-modal" role="dialog" aria-modal="true" aria-labelledby="dispense-title">
        <button className="modal-close" type="button" onClick={onCancel} aria-label="关闭取药确认">
          <X size={24} aria-hidden="true" />
        </button>

        <div className="modal-heading">
          <span aria-hidden="true">
            <ShieldCheck size={34} strokeWidth={2.1} />
          </span>
          <div>
            <p>取药确认</p>
            <h2 id="dispense-title">{medicine.name}</h2>
          </div>
        </div>

        <div className="modal-medicine-meta">
          <article>
            <span>柜门</span>
            <strong>{medicine.hardware_slot || medicine.slot}</strong>
          </article>
          <article>
            <span>库存</span>
            <strong>
              {medicine.stock}
              {medicine.unit}
            </strong>
          </article>
          <article>
            <span>有效期</span>
            <strong>{medicine.expire_date}</strong>
          </article>
        </div>

        <label className="quantity-control" htmlFor="dispense-quantity">
          <span>数量</span>
          <div>
            <button type="button" onClick={() => changeQuantity(quantity - 1)} aria-label="减少数量">
              <Minus size={22} aria-hidden="true" />
            </button>
            <input
              id="dispense-quantity"
              type="number"
              min="1"
              max={medicine.stock}
              value={quantity}
              onChange={(event) => changeQuantity(Number(event.target.value) || 1)}
            />
            <button type="button" onClick={() => changeQuantity(quantity + 1)} aria-label="增加数量">
              <Plus size={22} aria-hidden="true" />
            </button>
          </div>
        </label>

        <div className="modal-warning">
          <strong>禁忌提醒</strong>
          <ul>
            {medicine.contraindications.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>

        <p className="modal-safety">{medicine.safety_note}</p>

        <label className="confirm-check" htmlFor="safety-confirmed">
          <input
            id="safety-confirmed"
            type="checkbox"
            checked={checked}
            onChange={(event) => setChecked(event.target.checked)}
          />
          <span>我已阅读药品说明与安全提示，并确认现场可开柜</span>
        </label>

        {error && <p className="modal-message error">{error}</p>}
        {result && <p className="modal-message success">{result}</p>}

        <div className="modal-actions">
          <button className="secondary-action" type="button" onClick={onCancel}>
            取消
          </button>
          <button className="primary-action" type="button" disabled={!checked || submitting} onClick={handleSubmit}>
            {submitting ? "开柜中..." : "确认并开柜"}
          </button>
        </div>
      </section>
    </div>
  );
}
