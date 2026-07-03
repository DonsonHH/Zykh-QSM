import React from "react";
import { Activity, PackageOpen, Thermometer } from "lucide-react";

const icons = {
  cabinet: PackageOpen,
  temperature: Thermometer,
  device: Activity
};

export function HomeStatusStrip({ stats }) {
  return (
    <section className="stat-strip" aria-label="站点状态摘要">
      {(stats || []).map((stat) => {
        const Icon = icons[stat.id] || Activity;
        return (
          <article key={stat.id} className={`stat-item ${stat.tone || "soft"}`}>
            <Icon size={24} aria-hidden="true" />
            <span>{stat.label}</span>
            <strong>
              {stat.value}
              {stat.unit && <small>{stat.unit}</small>}
            </strong>
          </article>
        );
      })}
    </section>
  );
}
