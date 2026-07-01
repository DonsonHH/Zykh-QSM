import React from "react";
import { Droplets, HeartPulse, Thermometer } from "lucide-react";

export function VitalReadout({ vitals = {} }) {
  const items = [
    { icon: HeartPulse, label: "心率", value: vitals.heart_rate || "--", unit: "次/分", tone: "pink" },
    { icon: Droplets, label: "血氧", value: vitals.spo2 || "--", unit: "%", tone: "blue" },
    { icon: Thermometer, label: "体温", value: vitals.temperature || "--", unit: "℃", tone: "green" }
  ];

  return (
    <div className="vital-readout">
      {items.map(({ icon: Icon, label, value, unit, tone }) => (
        <div key={label} className={tone}>
          <Icon size={20} />
          <span>{label}</span>
          <strong>{value}</strong>
          <small>{unit}</small>
        </div>
      ))}
    </div>
  );
}
