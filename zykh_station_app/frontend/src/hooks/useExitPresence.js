import { useEffect, useState } from "react";

export function useExitPresence(open, duration = 170) {
  const [present, setPresent] = useState(Boolean(open));
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    let timer;
    if (open) {
      setPresent(true);
      setExiting(false);
    } else if (present) {
      setExiting(true);
      timer = window.setTimeout(() => {
        setPresent(false);
        setExiting(false);
      }, duration);
    }
    return () => window.clearTimeout(timer);
  }, [duration, open, present]);

  return { present, exiting };
}
