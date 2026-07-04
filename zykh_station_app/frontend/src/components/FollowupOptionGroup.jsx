import React from "react";

export function FollowupOptionGroup({ title, options, value, onChange, children }) {
  return (
    <section className="followup-option-group">
      <h3>{title}</h3>
      <div className="followup-option-row">
        {options.map((option) => {
          const label = typeof option === "string" ? option : option.label;
          const nextValue = typeof option === "string" ? option : option.value;
          return (
            <button
              key={nextValue}
              type="button"
              className={value === nextValue ? "active" : ""}
              onClick={() => onChange(nextValue)}
            >
              {label}
            </button>
          );
        })}
      </div>
      {children}
    </section>
  );
}
