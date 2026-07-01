import React from "react";

export function MarkdownText({ text }) {
  if (!text) return <p className="muted">正在生成...</p>;
  return String(text)
    .split(/\n+/)
    .map((line, idx) => {
      const clean = line.trim();
      if (!clean) return null;
      if (clean.startsWith("#")) return <strong key={idx}>{clean.replace(/^#+\s*/, "")}</strong>;
      if (/^[-*]\s+/.test(clean)) return <p key={idx}>• {clean.replace(/^[-*]\s+/, "")}</p>;
      const parts = clean.split(/(\*\*.*?\*\*)/g).filter(Boolean);
      return (
        <p key={idx}>
          {parts.map((part, i) => (part.startsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part))}
        </p>
      );
    });
}
