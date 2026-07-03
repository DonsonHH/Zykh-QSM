import React from "react";
import { ShieldCheck } from "lucide-react";

export function SafetyNotice({ children, tone = "blue" }) {
  return (
    <div className={`safety-notice ${tone}`}>
      <ShieldCheck size={21} aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}
