import React from "react";

export function PrimaryCard({ className = "", icon, title, children, actionLabel, onAction }) {
  return (
    <section className={`primary-card ${className}`}>
      <div className="card-icon" aria-hidden="true">
        {icon}
      </div>
      <div className="primary-card-body">
        <h2>{title}</h2>
        {children}
      </div>
      {actionLabel && (
        <button className="primary-action" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </section>
  );
}
