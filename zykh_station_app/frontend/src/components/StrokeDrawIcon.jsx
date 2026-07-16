import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

const drawableSelector = "path, circle, ellipse, line, polyline, polygon, rect";
const DRAW_PHASE_MS = 1600;
const DRAW_CYCLE_MS = DRAW_PHASE_MS * 2;
const DRAW_SEGMENT_MS = 900;
const DRAW_HOLD_MS = 240;
const IDLE_DRAW_PHASE_MS = 2500;
const IDLE_DRAW_CYCLE_MS = IDLE_DRAW_PHASE_MS * 2;
const IDLE_DRAW_SEGMENT_MS = 1400;
const IDLE_DRAW_HOLD_MS = 400;

export function StrokeDrawIcon({
  icon: Icon,
  size = 32,
  strokeWidth = 2,
  className = "",
  delay = 0,
  mode = "once",
  active = true,
  replayOnPointer = false,
  pace = "standard",
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

    const idlePace = pace === "idle";
    const phaseDuration = idlePace ? IDLE_DRAW_PHASE_MS : DRAW_PHASE_MS;
    const cycleDuration = idlePace ? IDLE_DRAW_CYCLE_MS : DRAW_CYCLE_MS;
    const segmentDuration = idlePace ? IDLE_DRAW_SEGMENT_MS : DRAW_SEGMENT_MS;
    const holdDuration = idlePace ? IDLE_DRAW_HOLD_MS : DRAW_HOLD_MS;

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
    const sequenceDuration = phaseDuration - holdDuration;
    const stagger =
      parts.length > 1 ? Math.max(0, sequenceDuration - segmentDuration) / (parts.length - 1) : 0;
    parts.forEach((part, index) => {
      part.setAttribute("pathLength", "1");
      part.style.setProperty("--stroke-draw-delay", `${delay + index * stagger}ms`);
      part.style.setProperty("--stroke-draw-duration", `${segmentDuration}ms`);
    });

    if (typeof parts[0]?.animate === "function") {
      setProgrammatic(mode === "once");
      setLooping(mode === "yoyo");
      const animations = parts.map((part, index) => {
        const drawStart = index * stagger;
        const drawEnd = drawStart + segmentDuration;
        const eraseStart = phaseDuration + drawStart;
        const eraseEnd = eraseStart + segmentDuration;
        const keyframes =
          mode === "yoyo"
            ? [
                { strokeDashoffset: 1, opacity: 0.24, offset: 0 },
                {
                  strokeDashoffset: 1,
                  opacity: 0.24,
                  offset: drawStart / cycleDuration,
                  easing: "linear"
                },
                { strokeDashoffset: 0, opacity: 1, offset: drawEnd / cycleDuration },
                {
                  strokeDashoffset: 0,
                  opacity: 1,
                  offset: eraseStart / cycleDuration,
                  easing: "linear"
                },
                { strokeDashoffset: -1, opacity: 1, offset: eraseEnd / cycleDuration },
                { strokeDashoffset: -1, opacity: 1, offset: 1 }
              ]
            : [
                { strokeDashoffset: 1, opacity: 0.24, offset: 0 },
                {
                  strokeDashoffset: 1,
                  opacity: 0.24,
                  offset: drawStart / phaseDuration,
                  easing: "linear"
                },
                { strokeDashoffset: 0, opacity: 1, offset: drawEnd / phaseDuration },
                { strokeDashoffset: 0, opacity: 1, offset: 1 }
              ];
        part.style.strokeDasharray = "1";
        part.style.strokeDashoffset = "1";
        part.style.opacity = "0.24";
        return part.animate(keyframes, {
          delay,
          direction: "normal",
          duration: mode === "yoyo" ? cycleDuration : phaseDuration,
          fill: "both",
          iterations: mode === "yoyo" ? Infinity : 1
        });
      });

      let timer;
      if (mode === "once") {
        timer = window.setTimeout(() => {
          animations.forEach((animation) => animation.cancel());
          resetParts();
          setProgrammatic(false);
          setComplete(true);
        }, delay + phaseDuration);
      }

      return () => {
        window.clearTimeout(timer);
        animations.forEach((animation) => animation.cancel());
        resetParts();
      };
    }

    setProgrammatic(false);
    setLooping(false);
    const totalDuration = delay + phaseDuration;
    const timer = window.setTimeout(() => setComplete(true), totalDuration);
    return () => {
      window.clearTimeout(timer);
      resetParts();
    };
  }, [Icon, active, delay, mode, pace, replayToken]);

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
