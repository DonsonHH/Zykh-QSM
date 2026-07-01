import { useCallback, useRef, useState } from "react";

export function useAsyncAction(action) {
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  const run = useCallback(
    async (...args) => {
      if (busyRef.current) return undefined;
      busyRef.current = true;
      setBusy(true);
      try {
        return await action(...args);
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [action]
  );

  return [run, busy];
}
