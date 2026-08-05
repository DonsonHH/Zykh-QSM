import { useEffect, useState } from "react";

const boundarySettleMs = 20;

export function millisecondsUntilNextMinute(now) {
  return 60_000 - (now.getSeconds() * 1000 + now.getMilliseconds()) + boundarySettleMs;
}

export function useMinuteClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let timer = 0;
    const schedule = () => {
      window.clearTimeout(timer);
      const current = new Date();
      timer = window.setTimeout(() => {
        setNow(new Date());
        schedule();
      }, millisecondsUntilNextMinute(current));
    };
    const refreshVisibleClock = () => {
      if (document.visibilityState !== "visible") return;
      setNow(new Date());
      schedule();
    };
    schedule();
    document.addEventListener("visibilitychange", refreshVisibleClock);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", refreshVisibleClock);
    };
  }, []);

  return now;
}
