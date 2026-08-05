const textInputTypes = new Set(["", "text", "search", "password", "email", "tel", "url", "number"]);

export function findTouchEditable(event) {
  const origin = event.target instanceof Element ? event.target : null;
  if (!origin) return null;
  const direct = origin.closest("input, textarea, [contenteditable='true']");
  const labelled = origin.closest("[data-touch-editable]")?.querySelector("input, textarea, [contenteditable='true']");
  const editable = direct || labelled;
  return isTextEditable(editable) ? editable : null;
}

export function isTextEditable(element) {
  if (!element || element.disabled || element.readOnly) return false;
  if (element instanceof HTMLTextAreaElement || element.isContentEditable) return true;
  return element instanceof HTMLInputElement && textInputTypes.has(element.type);
}

export function touchKeyboardMode(element) {
  if (!element) return "text";
  const inputMode = element.getAttribute("inputmode") || "";
  return element instanceof HTMLInputElement && (
    element.type === "number" || inputMode === "numeric" || inputMode === "decimal"
  ) ? "numeric" : "text";
}

export function replaceTouchSelection(element, replacement, inputType = "insertText") {
  if (!isTextEditable(element)) return false;
  if (element.isContentEditable) {
    element.focus({ preventScroll: true });
    return document.execCommand("insertText", false, replacement);
  }
  const start = element.selectionStart ?? element.value.length;
  const end = element.selectionEnd ?? start;
  const nextValue = `${element.value.slice(0, start)}${replacement}${element.value.slice(end)}`;
  const prototype = element instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(element, nextValue);
  element.dispatchEvent(new InputEvent("input", {
    bubbles: true,
    data: replacement,
    inputType
  }));
  const cursor = start + replacement.length;
  window.requestAnimationFrame(() => {
    if (!element.isConnected) return;
    element.focus({ preventScroll: true });
    element.setSelectionRange?.(cursor, cursor);
  });
  return true;
}

export function deleteTouchSelection(element) {
  if (!isTextEditable(element)) return false;
  if (element.isContentEditable) {
    element.focus({ preventScroll: true });
    return document.execCommand("delete", false);
  }
  const start = element.selectionStart ?? element.value.length;
  const end = element.selectionEnd ?? start;
  if (start !== end) return replaceRange(element, start, end, "", "deleteContentBackward");
  if (start <= 0) return true;
  return replaceRange(element, start - 1, start, "", "deleteContentBackward");
}

function replaceRange(element, start, end, replacement, inputType) {
  const nextValue = `${element.value.slice(0, start)}${replacement}${element.value.slice(end)}`;
  const prototype = element instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(element, nextValue);
  element.dispatchEvent(new InputEvent("input", { bubbles: true, data: replacement, inputType }));
  const cursor = start + replacement.length;
  window.requestAnimationFrame(() => {
    if (!element.isConnected) return;
    element.focus({ preventScroll: true });
    element.setSelectionRange?.(cursor, cursor);
  });
  return true;
}
