import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

const drawableSelector = "path, circle, ellipse, line, polyline, polygon, rect";
const DRAW_PHASE_MS = 1600;
const DRAW_SEGMENT_MS = 900;
const DRAW_HOLD_MS = 240;

export function StrokeDrawIcon({
  icon: Icon,
  size = 32,
  strokeWidth = 2,
  className = "",
  delay = 0,
  mode = "once",
  active = true,
  replayOnPointer = false,
  label
}) {
  const rootRef = useRef(null);
  const [complete, setComplete] = useState(false);
  const [looping, setLooping] = useState(mode === "yoyo" && active);
  const [programmatic, setProgrammatic] = useState(mode === "once" && active);
  const [replayToken, setReplayToken] = useState(0);

  useEffect(() => {
    if (!replayOnPointer) {
      return undefined;
    }
    const replay = (event) => {
      if (event.isPrimary === false || (event.pointerType === "mouse" && event.button !== 0)) {
        return;
      }
      setReplayToken((current) => current + 1);
    };
    const options = { capture: true, passive: true };
    document.addEventListener("pointerdown", replay, options);
    return () => document.removeEventListener("pointerdown", replay, true);
  }, [replayOnPointer]);

  useLayoutEffect(() => {
    const root = rootRef.current;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (!root) {
      return undefined;
    }

    const parts = [...root.querySelectorAll(drawableSelector)];
    const resetParts = () => {
      parts.forEach((part) => {
        part.style.removeProperty("stroke-dasharray");
        part.style.removeProperty("stroke-dashoffset");
        part.style.removeProperty("opacity");
        part.style.removeProperty("--stroke-draw-delay");
        part.style.removeProperty("--stroke-draw-duration");
      });
    };

    resetParts();
    if (reducedMotion || !active || parts.length === 0) {
      setProgrammatic(false);
      setLooping(false);
      setComplete(true);
      return resetParts;
    }

    setComplete(false);
    const sequenceDuration = DRAW_PHASE_MS - DRAW_HOLD_MS;
    const stagger =
      parts.length > 1 ? Math.max(0, sequenceDuration - DRAW_SEGMENT_MS) / (parts.length - 1) : 0;
    parts.forEach((part, index) => {
      part.setAttribute("pathLength", "1");
      part.style.setProperty("--stroke-draw-delay", `${delay + index * stagger}ms`);
      part.style.setProperty("--stroke-draw-duration", `${DRAW_SEGMENT_MS}ms`);
    });

    if (typeof parts[0]?.animate === "function") {
      setProgrammatic(mode === "once");
      setLooping(mode === "yoyo");
      const animations = parts.map((part, index) => {
        const startOffset = (index * stagger) / DRAW_PHASE_MS;
        const endOffset = (index * stagger + DRAW_SEGMENT_MS) / DRAW_PHASE_MS;
        part.style.strokeDasharray = "1";
        part.style.strokeDashoffset = "1";
        part.style.opacity = "0.24";
        return part.animate(
          [
            { strokeDashoffset: 1, opacity: 0.24, offset: 0 },
            { strokeDashoffset: 1, opacity: 0.24, offset: startOffset, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
            { strokeDashoffset: 0, opacity: 1, offset: endOffset },
            { strokeDashoffset: 0, opacity: 1, offset: 1 }
          ],
          {
            delay,
            direction: mode === "yoyo" ? "alternate" : "normal",
            duration: DRAW_PHASE_MS,
            fill: "both",
            iterations: mode === "yoyo" ? Infinity : 1
          }
        );
      });

      let timer;
      if (mode === "once") {
        timer = window.setTimeout(() => {
          animations.forEach((animation) => animation.cancel());
          resetParts();
          setProgrammatic(false);
          setComplete(true);
        }, delay + DRAW_PHASE_MS);
      }

      return () => {
        window.clearTimeout(timer);
        animations.forEach((animation) => animation.cancel());
        resetParts();
      };
    }

    setProgrammatic(false);
    setLooping(false);
    const totalDuration = delay + DRAW_PHASE_MS;
    const timer = window.setTimeout(() => setComplete(true), totalDuration);
    return () => {
      window.clearTimeout(timer);
      resetParts();
    };
  }, [Icon, active, delay, mode, replayToken]);

  return (
    <span
      ref={rootRef}
      className={`stroke-draw-icon ${programmatic ? "is-programmatic" : looping ? "is-yoyo" : complete ? "is-complete" : "is-drawing"} ${className}`.trim()}
      style={{ "--stroke-icon-size": typeof size === "number" ? `${size}px` : size }}
      role={label ? "img" : undefined}
      aria-label={label || undefined}
      aria-hidden={label ? undefined : "true"}
    >
      <Icon size={size} strokeWidth={strokeWidth} aria-hidden="true" />
    </span>
  );
}
