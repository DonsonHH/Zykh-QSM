import React, { useEffect, useRef, useState } from "react";
import { Plane } from "lucide-react";
import { getNetworkIndicators } from "../utils/network.js";
import { NETWORK_ACTIVITY_EVENT } from "../utils/networkActivity.js";

const activityHoldMs = 900;

export function NetworkStatusIcons({ networkStatus, variant = "header" }) {
  const { pending, localMode, activeTransport, wifi, sim } = getNetworkIndicators(networkStatus);
  const activity = useNetworkActivity();

  if (pending) {
    return (
      <div className={`network-icons ${variant} single-link pending`} role="group" aria-label="正在检测 WiFi 状态">
        <NetworkLink
          kind="wifi"
          connected={false}
          bars={0}
          tone="pending"
          label="正在检测 WiFi"
          active={false}
          pending
          activity={activity}
        />
      </div>
    );
  }

  if (localMode) {
    return (
      <div className={`network-icons ${variant} local-only`} role="group" aria-label="本地离线模式">
        <span className="network-link local" aria-label="本地离线模式">
          <Plane size={29} strokeWidth={2.2} aria-hidden="true" />
        </span>
      </div>
    );
  }

  return (
    <div className={`network-icons ${variant} ${sim.enabled ? "" : "single-link"}`} role="group" aria-label="网络状态">
      <NetworkLink
        kind="wifi"
        connected={wifi.connected}
        bars={wifi.bars}
        tone={wifi.tone}
        label={wifi.label}
        active={activeTransport === "wifi"}
        activity={activity}
      />
      {sim.enabled ? (
        <NetworkLink
          kind="sim"
          connected={sim.connected}
          bars={sim.bars}
          tone={sim.tone}
          label={sim.label}
          active={activeTransport === "sim"}
          activity={activity}
        />
      ) : null}
    </div>
  );
}

function NetworkLink({ kind, connected, bars, tone, label, active, pending = false, activity }) {
  const accessibleLabel = `${label}${active ? "，当前使用" : ""}`;
  return (
    <span
      className={`network-link ${kind} ${tone} ${active ? "active-transport" : ""}`}
      aria-label={accessibleLabel}
    >
      {kind === "wifi" ? (
        <WifiSignalGlyph connected={connected} bars={bars} pending={pending} />
      ) : (
        <Cellular4GGlyph connected={connected} bars={bars} />
      )}
      <span className="network-transfer" aria-hidden="true">
        <span className={`network-transfer-triangle upload ${active && activity.upload ? "is-live" : ""}`} />
        <span className={`network-transfer-triangle download ${active && activity.download ? "is-live" : ""}`} />
      </span>
    </span>
  );
}

function WifiSignalGlyph({ connected, bars, pending = false }) {
  const level = connected ? Math.max(0, Math.min(4, Number(bars) || 0)) : 0;
  return (
    <svg className="wifi-signal-glyph" viewBox="0 0 34 32" aria-hidden="true">
      <path className={level >= 4 ? "is-on" : ""} d="M3.5 10.5c7.5-6.7 19.5-6.7 27 0" />
      <path className={level >= 3 ? "is-on" : ""} d="M8 16c5-4.5 13-4.5 18 0" />
      <path className={level >= 2 ? "is-on" : ""} d="M12.5 21.5c2.5-2.1 6.5-2.1 9 0" />
      <circle className={level >= 1 ? "is-on" : ""} cx="17" cy="26" r="2" />
      {!connected && !pending ? <path className="network-slash" d="M5 5 29 29" /> : null}
    </svg>
  );
}

function Cellular4GGlyph({ connected, bars }) {
  const level = connected ? Math.max(0, Math.min(4, Number(bars) || 0)) : 0;
  return (
    <svg className="cellular-signal-glyph" viewBox="0 0 42 32" aria-hidden="true">
      {[1, 2, 3, 4].map((bar) => (
        <rect
          key={bar}
          className={level >= bar ? "is-on" : ""}
          x={2 + (bar - 1) * 5}
          y={27 - bar * 5}
          width="3.5"
          height={bar * 5}
          rx="1.2"
        />
      ))}
      <text x="23" y="20">4G</text>
      {!connected ? <path className="network-slash" d="M3 5 38 29" /> : null}
    </svg>
  );
}

function useNetworkActivity() {
  const [activity, setActivity] = useState({ upload: false, download: false });
  const timers = useRef({ upload: 0, download: 0 });

  useEffect(() => {
    const handleActivity = (event) => {
      const direction = event.detail?.direction;
      if (direction !== "upload" && direction !== "download") {
        return;
      }
      window.clearTimeout(timers.current[direction]);
      setActivity((current) => ({ ...current, [direction]: true }));
      timers.current[direction] = window.setTimeout(() => {
        setActivity((current) => ({ ...current, [direction]: false }));
      }, activityHoldMs);
    };
    window.addEventListener(NETWORK_ACTIVITY_EVENT, handleActivity);
    return () => {
      window.removeEventListener(NETWORK_ACTIVITY_EVENT, handleActivity);
      window.clearTimeout(timers.current.upload);
      window.clearTimeout(timers.current.download);
    };
  }, []);

  return activity;
}
