import { useCallback, useEffect, useRef, useState } from "react";
import { resolveIdentity } from "../api/identity.js";

const storageKey = "zykh-active-face-identity";

export function activateIdentity(identity) {
  try {
    if (identity) {
      window.sessionStorage.setItem(storageKey, JSON.stringify(identity));
    } else {
      window.sessionStorage.removeItem(storageKey);
    }
  } catch {
    // Session storage is optional.
  }
  window.dispatchEvent(new CustomEvent("zykh-identity-change", { detail: identity || null }));
}

function readStoredIdentity() {
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function useFaceIdentity({ auto = true, activateOnMatch = true } = {}) {
  const [identity, setIdentity] = useState(() => readStoredIdentity());
  const [status, setStatus] = useState(identity ? "matched" : "idle");
  const [message, setMessage] = useState(identity ? `已确认使用人：${identity.name}` : "等待确认使用人");
  const identifyPromiseRef = useRef(null);
  const identityGenerationRef = useRef(0);

  const identify = useCallback(async ({ force = false } = {}) => {
    if (identifyPromiseRef.current) {
      return identifyPromiseRef.current;
    }
    const stored = force ? null : readStoredIdentity();
    if (stored) {
      setIdentity(stored);
      setStatus("matched");
      setMessage(`已确认使用人：${stored.name}`);
      return { ok: true, status: "matched", user: stored };
    }
    const generation = identityGenerationRef.current;
    const request = (async () => {
      setStatus("identifying");
      setMessage("");
      try {
        const result = await resolveIdentity();
        if (generation !== identityGenerationRef.current) {
          return { ...result, ok: false, status: "superseded", message: "身份确认已重新开始。" };
        }
        if (result.ok && result.user) {
          setIdentity(result.user);
          setStatus(result.status || "matched");
          setMessage(result.message || `已确认使用人：${result.user.name}`);
          if (activateOnMatch) {
            activateIdentity(result.user);
          }
          return result;
        }
        setStatus(result.status || "unavailable");
        setMessage(result.error_message || result.message || "暂时无法确认使用人");
        return result;
      } catch (error) {
        if (generation === identityGenerationRef.current) {
          setStatus("unavailable");
          setMessage(error.message || "人脸识别暂不可用");
        }
        throw error;
      }
    })();
    identifyPromiseRef.current = request;
    try {
      return await request;
    } finally {
      if (identifyPromiseRef.current === request) {
        identifyPromiseRef.current = null;
      }
    }
  }, [activateOnMatch]);

  const clear = useCallback(() => {
    identityGenerationRef.current += 1;
    identifyPromiseRef.current = null;
    try {
      window.sessionStorage.removeItem(storageKey);
    } catch {
      // Session storage is optional.
    }
    setIdentity(null);
    setStatus("idle");
    setMessage("等待确认使用人");
    window.dispatchEvent(new CustomEvent("zykh-identity-change", { detail: null }));
  }, []);

  useEffect(() => {
    if (auto && !identity && status === "idle") {
      identify().catch(() => {
        // identify() owns status updates and ignores superseded requests.
      });
    }
  }, [auto, identify, identity, status]);

  useEffect(() => {
    function syncIdentity(event) {
      const next = event.detail || null;
      setIdentity(next);
      setStatus(next ? "matched" : "idle");
      setMessage(next ? `已确认使用人：${next.name}` : "等待确认使用人");
    }
    window.addEventListener("zykh-identity-change", syncIdentity);
    return () => window.removeEventListener("zykh-identity-change", syncIdentity);
  }, []);

  return { identity, status, message, identify, clear };
}
