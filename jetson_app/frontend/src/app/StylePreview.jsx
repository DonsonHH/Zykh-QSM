import React from "react";
import { Bot, Camera, CheckCircle2, Pill, ShieldCheck } from "lucide-react";
import { BigActionButton } from "../components/BigActionButton.jsx";
import { GlassCard } from "../components/GlassCard.jsx";
import { StatusPill } from "../components/StatusPill.jsx";

const swatches = [
  ["蓝色", "var(--accent-blue)"],
  ["青色", "var(--accent-cyan)"],
  ["绿色", "var(--accent-green)"],
  ["紫色", "var(--accent-purple)"],
  ["橙色", "var(--accent-orange)"],
  ["红色", "var(--accent-red)"]
];

export function StylePreview() {
  return (
    <main className="viewport">
      <section className="style-preview kiosk-canvas" style={{ "--kiosk-scale": 1 }}>
        <header>
          <div>
            <span className="card-eyebrow">UI Style Preview</span>
            <h1>智药康护终端视觉规范</h1>
          </div>
          <div className="style-status-row">
            <StatusPill icon={ShieldCheck} label="系统状态" value="正常" tone="good" />
            <StatusPill icon={Camera} label="摄像头" value="暂不可用" tone="soft" />
          </div>
        </header>
        <div className="style-grid">
          <GlassCard>
            <span className="card-eyebrow">Buttons</span>
            <div className="style-button-stack">
              <BigActionButton icon={Pill} title="开始取药" detail="校验计划后开仓" tone="orange" />
              <BigActionButton icon={Bot} title="开始问诊" detail="支持文字与语音" tone="purple" />
              <BigActionButton icon={CheckCircle2} title="确认保存" detail="主操作蓝色" tone="blue" />
              <BigActionButton icon={Camera} title="暂不可用" detail="设备连接中" tone="blue" disabled />
            </div>
          </GlassCard>
          <GlassCard>
            <span className="card-eyebrow">Form</span>
            <label>药品名称<input defaultValue="阿司匹林肠溶片" /></label>
            <label>备注<textarea defaultValue="饭后服用，注意漏服提醒。" /></label>
          </GlassCard>
          <GlassCard>
            <span className="card-eyebrow">Colors</span>
            <div className="swatch-grid">
              {swatches.map(([label, color]) => (
                <p key={label}>
                  <i style={{ background: color }} />
                  <span>{label}</span>
                </p>
              ))}
            </div>
          </GlassCard>
        </div>
      </section>
    </main>
  );
}
