import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowBigUp, Delete, Keyboard, Space, X } from "lucide-react";
import {
  deleteTouchSelection,
  findTouchEditable,
  isTextEditable,
  replaceTouchSelection,
  touchKeyboardMode
} from "../utils/touchKeyboard.js";

const textRows = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["shift", "z", "x", "c", "v", "b", "n", "m", "backspace"],
  ["comma", "space", "period", "done"]
];

const numericRows = [
  ["1", "2", "3", "backspace"],
  ["4", "5", "6", "clear"],
  ["7", "8", "9", "done"],
  ["0"]
];

function targetLabel(element) {
  if (!element) return "文本";
  const explicit = element.getAttribute("aria-label");
  if (explicit) return explicit;
  const label = element.closest("label")?.querySelector("span")?.textContent?.trim();
  return label || element.getAttribute("placeholder") || "文本";
}

export function TouchKeyboard({ enabled = true }) {
  const targetRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("text");
  const [shifted, setShifted] = useState(false);
  const [label, setLabel] = useState("文本");

  useEffect(() => {
    if (!enabled) return undefined;
    const showForElement = (editable) => {
      targetRef.current = editable;
      setMode(touchKeyboardMode(editable));
      setShifted(false);
      setLabel(targetLabel(editable));
      setOpen(true);
      window.requestAnimationFrame(() => {
        editable.focus({ preventScroll: false });
        editable.scrollIntoView?.({ block: "center", inline: "nearest", behavior: "instant" });
      });
    };
    const showForEvent = (event) => {
      if (event.target instanceof Element && event.target.closest("[data-touch-keyboard]")) return;
      const editable = findTouchEditable(event);
      if (!editable) {
        if (event.type === "pointerdown") setOpen(false);
        return;
      }
      showForElement(editable);
    };
    document.addEventListener("pointerdown", showForEvent, true);
    document.addEventListener("focusin", showForEvent, true);
    if (isTextEditable(document.activeElement)) showForElement(document.activeElement);
    return () => {
      document.removeEventListener("pointerdown", showForEvent, true);
      document.removeEventListener("focusin", showForEvent, true);
    };
  }, [enabled]);

  useEffect(() => {
    document.documentElement.classList.toggle("touch-keyboard-open", enabled && open);
    return () => document.documentElement.classList.remove("touch-keyboard-open");
  }, [enabled, open]);

  const rows = useMemo(() => mode === "numeric" ? numericRows : textRows, [mode]);

  function close() {
    setOpen(false);
    targetRef.current?.blur?.();
  }

  function press(key) {
    const target = targetRef.current;
    if (!isTextEditable(target) || !target.isConnected) {
      setOpen(false);
      return;
    }
    if (key === "shift") {
      setShifted((current) => !current);
      return;
    }
    if (key === "backspace") {
      deleteTouchSelection(target);
      return;
    }
    if (key === "clear") {
      target.select?.();
      replaceTouchSelection(target, "", "deleteContentBackward");
      return;
    }
    if (key === "done") {
      close();
      return;
    }
    const value = key === "space" ? " " : key === "comma" ? "，" : key === "period" ? "。" : key;
    replaceTouchSelection(target, shifted ? value.toUpperCase() : value);
    if (shifted && /^[a-z]$/.test(value)) setShifted(false);
  }

  if (!enabled || !open) return null;

  return createPortal(
    <section
      className={`touch-keyboard touch-keyboard-${mode}`}
      data-touch-keyboard
      data-mode={mode}
      role="group"
      aria-label="屏幕键盘"
      onPointerDown={(event) => event.preventDefault()}
    >
      <header className="touch-keyboard-header">
        <span><Keyboard size={20} aria-hidden="true" />正在输入：{label}</span>
        <button type="button" onClick={close} aria-label="关闭屏幕键盘"><X size={23} /></button>
      </header>
      <div className="touch-keyboard-rows">
        {rows.map((row, rowIndex) => (
          <div className="touch-keyboard-row" key={`${mode}-${rowIndex}`}>
            {row.map((key) => {
              const isLetter = /^[a-z]$/.test(key);
              const display = isLetter && shifted ? key.toUpperCase() : key;
              return (
                <button
                  type="button"
                  key={key}
                  className={`touch-key touch-key-${key}${key === "shift" && shifted ? " active" : ""}`}
                  data-key={key}
                  aria-label={key === "backspace" ? "退格" : key === "shift" ? "大写" : undefined}
                  onClick={() => press(key)}
                >
                  {key === "backspace" ? <Delete size={25} />
                    : key === "shift" ? <ArrowBigUp size={25} />
                      : key === "space" ? <><Space size={24} /><span>空格</span></>
                        : key === "done" ? "完成"
                          : key === "clear" ? "清空"
                            : key === "comma" ? "，"
                              : key === "period" ? "。"
                                : display}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </section>,
    document.body
  );
}
