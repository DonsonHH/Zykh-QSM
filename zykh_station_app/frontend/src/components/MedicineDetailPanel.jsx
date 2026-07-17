import React from "react";
import { CalendarDays, ClipboardList, PackageOpen, ShieldAlert, Stethoscope } from "lucide-react";
import { MedicineIcon } from "./MedicineIcon.jsx";

export function MedicineDetailPanel({ medicine, onConfirm }) {
  if (!medicine) {
    return (
      <aside className="medicine-detail-panel empty">
        <h2>药品信息</h2>
        <p>请选择左侧药品查看安全提示。</p>
      </aside>
    );
  }

  const isCareSupply = ["外伤护理", "消毒护理"].includes(medicine.category);

  return (
    <aside className="medicine-detail-panel">
      <div className="medicine-detail-scroll">
        <div className="detail-heading">
          <MedicineIcon medicine={medicine} size={34} className="detail-icon" />
          <div className="detail-heading-copy">
            <h2>{medicine.name}</h2>
            <p>
              {medicine.manufacturer ? <span className="detail-manufacturer">{medicine.manufacturer}</span> : null}
              <span className="detail-category">{medicine.category}</span>
              <span className="detail-slot">{medicine.hardware_slot || medicine.slot}号仓</span>
            </p>
          </div>
        </div>

        <section className="detail-section">
          <h3>
            <Stethoscope size={20} aria-hidden="true" />
            {isCareSupply ? "适用范围" : "功能主治"}
          </h3>
          <p className="detail-copy">{medicine.indications || medicine.tags.join("、") || "请核对药品包装说明。"}</p>
        </section>

        <section className="detail-section dosage-section">
          <h3>
            <ClipboardList size={20} aria-hidden="true" />
            {isCareSupply ? "使用方法" : "用法用量"}
          </h3>
          <p className="detail-copy">{medicine.dosage || "请按实物包装说明书或既往医嘱使用。"}</p>
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

        <p className={`detail-guidance-source ${medicine.guidance_review_required ? "review" : ""}`}>
          {medicine.guidance_source === "label_reference"
            ? "药品说明书参考"
            : medicine.guidance_source === "cloud_ai"
              ? "云端资料已补全"
              : medicine.guidance_source === "pending"
                ? "资料待补全"
                : "本机参考资料"}
          {medicine.guidance_review_required ? " · 使用前请核对实物包装说明书" : ""}
        </p>
      </div>

      <button className="primary-action detail-action" type="button" onClick={onConfirm}>
        取药
      </button>
    </aside>
  );
}
