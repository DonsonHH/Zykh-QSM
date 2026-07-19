const textInputTypes = new Set(["", "text", "search", "password", "email", "tel", "url", "number"]);

export function enableTouchKeyboardForEvent(event) {
  const origin = event.target instanceof Element ? event.target : null;
  if (!origin) return;
  const direct = origin.closest("input, textarea, [contenteditable='true']");
  const labelled = origin.closest("[data-touch-editable]")?.querySelector("input, textarea, [contenteditable='true']");
  const editable = direct || labelled;
  if (!isTextEditable(editable)) return;
  window.requestAnimationFrame(() => {
    editable.focus({ preventScroll: false });
    try {
      navigator.virtualKeyboard?.show?.();
    } catch {
      // The system keyboard can still react to the focused control through accessibility APIs.
    }
  });
}

function isTextEditable(element) {
  if (!element || element.disabled || element.readOnly) return false;
  if (element instanceof HTMLTextAreaElement || element.isContentEditable) return true;
  return element instanceof HTMLInputElement && textInputTypes.has(element.type);
}
