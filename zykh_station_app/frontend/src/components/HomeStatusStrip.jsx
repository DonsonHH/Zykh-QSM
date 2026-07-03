import React from "react";
import { Activity, PackageOpen, Thermometer } from "lucide-react";

const icons = {
  cabinet: PackageOpen,
  temperature: Thermometer,
  device: Activity
};

export function HomeStatusStrip({ stats, readingVitals, onReadVitals }) {
  return (
    <section className="stat-strip" aria-label="站点状态摘要">
      {(stats || []).map((stat) => {
        const Icon = icons[stat.id] || Activity;
        const clickable = stat.id === "temperature" && typeof onReadVitals === "function";
        const content = (
          <>
            <Icon size={24} aria-hidden="true" />
            <span>{stat.label}</span>
            <strong>
              {readingVitals && stat.id === "temperature" ? "读取中" : stat.value}
              {stat.unit && !(readingVitals && stat.id === "temperature") && <small>{stat.unit}</small>}
            </strong>
          </>
        );
        if (clickable) {
          return (
            <button
              key={stat.id}
              className={`stat-item stat-button ${stat.tone || "soft"}`}
              type="button"
              onClick={onReadVitals}
            >
              {content}
            </button>
          );
        }
        return (
          <article key={stat.id} className={`stat-item ${stat.tone || "soft"}`}>
            {content}
          </article>
        );
      })}
    </section>
  );
}
