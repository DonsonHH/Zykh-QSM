import React from "react";
import { CalendarDays, PackageOpen, ShieldAlert, Tags } from "lucide-react";

export function MedicineDetailPanel({ medicine, onConfirm }) {
  if (!medicine) {
    return (
      <aside className="medicine-detail-panel empty">
        <h2>药品信息</h2>
        <p>请选择左侧药品查看安全提示。</p>
      </aside>
    );
  }

  return (
    <aside className="medicine-detail-panel">
      <div className="detail-heading">
        <span className="detail-icon" aria-hidden="true">
          <PackageOpen size={34} strokeWidth={2.1} />
        </span>
        <div>
          <p>药品信息</p>
          <h2>{medicine.name}</h2>
        </div>
      </div>

      <div className="detail-pill-row">
        <span>{medicine.hardware_slot || medicine.slot}号仓</span>
        <span>{medicine.category}</span>
        <span>{medicine.is_otc ? "常备药" : "需核验"}</span>
        {medicine.is_emergency && <span>应急可用</span>}
      </div>

      <section className="detail-section">
        <h3>
          <Tags size={20} aria-hidden="true" />
          适用标签
        </h3>
        <div className="tag-list">
          {medicine.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>
          <ShieldAlert size={20} aria-hidden="true" />
          禁忌提醒
        </h3>
        <ul>
          {medicine.contraindications.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <div className="detail-stats">
        <article>
          <PackageOpen size={21} aria-hidden="true" />
          <span>库存</span>
          <strong>
            {medicine.stock}
            {medicine.unit}
          </strong>
        </article>
        <article>
          <CalendarDays size={21} aria-hidden="true" />
          <span>有效期</span>
          <strong>{medicine.expire_date}</strong>
        </article>
      </div>

      <button className="primary-action detail-action" type="button" onClick={onConfirm}>
        进入取药确认
      </button>
    </aside>
  );
}
