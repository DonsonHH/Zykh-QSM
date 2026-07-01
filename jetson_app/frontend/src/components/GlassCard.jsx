import React from "react";

export function GlassCard({ as: Tag = "section", className = "", children, ...props }) {
  return (
    <Tag className={`glass-card ${className}`.trim()} {...props}>
      {children}
    </Tag>
  );
}
