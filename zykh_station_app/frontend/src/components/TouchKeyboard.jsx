import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowBigUp, ChevronLeft, ChevronRight, Delete, GripHorizontal, Keyboard, Languages, Space, X } from "lucide-react";
import { loadPinyinEngine } from "../utils/pinyinIme.js";
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
  ["language", "comma", "space", "period", "done"]
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
  const keyboardRef = useRef(null);
  const compositionRef = useRef("");
  const languageRef = useRef("zh");
  const dragRef = useRef(null);
  const userDraggedRef = useRef(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("text");
  const [shifted, setShifted] = useState(false);
  const [label, setLabel] = useState("文本");
  const [language, setLanguage] = useState("zh");
  const [composition, setComposition] = useState("");
  const [engine, setEngine] = useState(null);
  const [dictionaryState, setDictionaryState] = useState("idle");
  const [candidatePage, setCandidatePage] = useState(0);
  const [position, setPosition] = useState(null);
  const [placementRequest, setPlacementRequest] = useState(0);

  function updateComposition(value) {
    compositionRef.current = value;
    setComposition(value);
    setCandidatePage(0);
  }

  function commitRawComposition(target = targetRef.current) {
    if (!compositionRef.current || !isTextEditable(target)) return;
    replaceTouchSelection(target, compositionRef.current);
    updateComposition("");
  }

  useEffect(() => {
    if (!enabled) return undefined;
    const showForElement = (editable) => {
      if (targetRef.current !== editable) commitRawComposition(targetRef.current);
      targetRef.current = editable;
      const nextMode = touchKeyboardMode(editable);
      setMode(nextMode);
      setShifted(false);
      if (nextMode === "text") {
        languageRef.current = "zh";
        setLanguage("zh");
      }
      updateComposition("");
      userDraggedRef.current = false;
      setPosition(null);
      setPlacementRequest((request) => request + 1);
      setLabel(targetLabel(editable));
      setOpen(true);
      window.requestAnimationFrame(() => {
        editable.focus({ preventScroll: true });
        const bounds = editable.getBoundingClientRect();
        if (bounds.top < 8 || bounds.bottom > window.innerHeight - 8) {
          editable.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "instant" });
        }
        window.requestAnimationFrame(() => setPlacementRequest((request) => request + 1));
      });
    };
    const showForEvent = (event) => {
      if (event.target instanceof Element && event.target.closest("[data-touch-keyboard]")) return;
      const editable = findTouchEditable(event);
      if (!editable) {
        if (event.type === "pointerdown") {
          commitRawComposition();
          setOpen(false);
        }
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
    if (!enabled || !open || mode !== "text" || language !== "zh" || engine) return undefined;
    let active = true;
    setDictionaryState("loading");
    loadPinyinEngine().then((loadedEngine) => {
      if (!active) return;
      setEngine(loadedEngine);
      setDictionaryState("ready");
    }).catch(() => {
      if (active) setDictionaryState("error");
    });
    return () => { active = false; };
  }, [enabled, engine, language, mode, open]);

  useLayoutEffect(() => {
    if (!enabled || !open) return undefined;
    const placeBesideTarget = () => {
      if (userDraggedRef.current) return;
      const keyboard = keyboardRef.current;
      const target = targetRef.current;
      if (!keyboard || !isTextEditable(target)) return;
      const keyboardBounds = keyboard.getBoundingClientRect();
      const targetBounds = target.getBoundingClientRect();
      const margin = 8;
      const gap = 12;
      const topY = margin;
      const bottomY = Math.max(margin, window.innerHeight - keyboardBounds.height - margin);
      const overlaps = (y) => targetBounds.bottom + gap > y && targetBounds.top - gap < y + keyboardBounds.height;
      const topSafe = !overlaps(topY);
      const bottomSafe = !overlaps(bottomY);
      let y;
      if (topSafe !== bottomSafe) y = topSafe ? topY : bottomY;
      else if (targetBounds.top >= window.innerHeight / 2) y = topY;
      else y = bottomY;
      const centeredX = (window.innerWidth - keyboardBounds.width) / 2;
      const x = Math.min(
        Math.max(margin, centeredX),
        Math.max(margin, window.innerWidth - keyboardBounds.width - margin)
      );
      setPosition({ x, y });
    };
    placeBesideTarget();
    window.addEventListener("resize", placeBesideTarget);
    return () => window.removeEventListener("resize", placeBesideTarget);
  }, [enabled, language, mode, open, placementRequest]);

  useEffect(() => {
    if (!enabled || !open) return undefined;
    const move = (event) => {
      const drag = dragRef.current;
      const keyboard = keyboardRef.current;
      if (!drag || !keyboard || event.pointerId !== drag.pointerId) return;
      const bounds = keyboard.getBoundingClientRect();
      const margin = 6;
      setPosition({
        x: Math.min(
          Math.max(margin, event.clientX - drag.offsetX),
          Math.max(margin, window.innerWidth - bounds.width - margin)
        ),
        y: Math.min(
          Math.max(margin, event.clientY - drag.offsetY),
          Math.max(margin, window.innerHeight - bounds.height - margin)
        )
      });
    };
    const stop = (event) => {
      if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
    };
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerup", stop, { passive: true });
    window.addEventListener("pointercancel", stop, { passive: true });
    return () => {
      dragRef.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, [enabled, open]);

  useEffect(() => {
    document.documentElement.classList.toggle("touch-keyboard-open", enabled && open);
    return () => document.documentElement.classList.remove("touch-keyboard-open");
  }, [enabled, open]);

  const rows = useMemo(() => mode === "numeric" ? numericRows : textRows, [mode]);
  const candidates = useMemo(
    () => composition && engine ? engine.getCandidates(composition).candidates : [],
    [composition, engine]
  );
  const pageSize = 5;
  const pageCount = Math.max(1, Math.ceil(candidates.length / pageSize));
  const visibleCandidates = candidates.slice(candidatePage * pageSize, (candidatePage + 1) * pageSize);

  function close({ preserveComposition = true } = {}) {
    if (preserveComposition) commitRawComposition();
    setOpen(false);
    targetRef.current?.blur?.();
  }

  function selectCandidate(candidate) {
    const target = targetRef.current;
    if (!candidate || !isTextEditable(target)) return;
    replaceTouchSelection(target, candidate.word);
    updateComposition(compositionRef.current.slice(candidate.matchedLength));
  }

  function commitFirstCandidate() {
    if (!compositionRef.current) return false;
    const firstCandidate = engine?.getCandidates(compositionRef.current).candidates[0];
    if (firstCandidate) selectCandidate(firstCandidate);
    else commitRawComposition();
    return true;
  }

  function startDragging(event) {
    if (event.target instanceof Element && event.target.closest("button")) return;
    const bounds = keyboardRef.current?.getBoundingClientRect();
    if (!bounds) return;
    userDraggedRef.current = true;
    dragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - bounds.left,
      offsetY: event.clientY - bounds.top
    };
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // Synthetic events and some X11 touch stacks do not expose pointer capture.
      // Window-level listeners still keep dragging functional.
    }
  }

  function press(key) {
    const target = targetRef.current;
    const currentLanguage = languageRef.current;
    if (!isTextEditable(target) || !target.isConnected) {
      setOpen(false);
      return;
    }
    if (key === "shift") {
      if (currentLanguage === "zh") return;
      setShifted((current) => !current);
      return;
    }
    if (key === "language") {
      commitRawComposition(target);
      const nextLanguage = currentLanguage === "zh" ? "en" : "zh";
      languageRef.current = nextLanguage;
      setLanguage(nextLanguage);
      setShifted(false);
      return;
    }
    if (key === "backspace") {
      if (currentLanguage === "zh" && compositionRef.current) {
        updateComposition(compositionRef.current.slice(0, -1));
        return;
      }
      deleteTouchSelection(target);
      return;
    }
    if (key === "clear") {
      target.select?.();
      replaceTouchSelection(target, "", "deleteContentBackward");
      return;
    }
    if (key === "done") {
      commitFirstCandidate();
      close();
      return;
    }
    const isLetter = /^[a-z]$/.test(key);
    if (mode === "text" && currentLanguage === "zh" && isLetter) {
      updateComposition(`${compositionRef.current}${key}`);
      return;
    }
    if (mode === "text" && currentLanguage === "zh" && key === "space" && commitFirstCandidate()) return;
    if (mode === "text" && currentLanguage === "zh" && (key === "comma" || key === "period")) {
      commitFirstCandidate();
    }
    const value = key === "space" ? " " : key === "comma" ? "，" : key === "period" ? "。" : key;
    replaceTouchSelection(target, shifted ? value.toUpperCase() : value);
    if (shifted && /^[a-z]$/.test(value)) setShifted(false);
  }

  if (!enabled || !open) return null;

  return createPortal(
    <section
      ref={keyboardRef}
      className={`touch-keyboard touch-keyboard-${mode}${position ? " touch-keyboard-positioned" : ""}`}
      data-touch-keyboard
      data-mode={mode}
      role="group"
      aria-label="屏幕键盘"
      style={position ? { left: position.x, top: position.y, bottom: "auto", transform: "none" } : undefined}
      onPointerDown={(event) => event.preventDefault()}
    >
      <header className="touch-keyboard-header" onPointerDown={startDragging}>
        <span><GripHorizontal size={22} aria-hidden="true" />拖动键盘</span>
        <span className="touch-keyboard-target"><Keyboard size={20} aria-hidden="true" />正在输入：{label}</span>
        <button type="button" onClick={close} aria-label="关闭屏幕键盘"><X size={23} /></button>
      </header>
      {mode === "text" && language === "zh" && (
        <div className="touch-keyboard-ime" aria-live="polite">
          <span className="touch-keyboard-composition" data-pinyin-composition>
            {composition || "请输入拼音"}
          </span>
          <div className="touch-keyboard-candidates" aria-label="拼音候选词">
            {visibleCandidates.map((candidate, index) => (
              <button
                type="button"
                key={`${candidate.word}-${index}`}
                data-pinyin-candidate
                onClick={() => selectCandidate(candidate)}
              >
                <small>{candidatePage * pageSize + index + 1}</small>{candidate.word}
              </button>
            ))}
            {!visibleCandidates.length && (
              <span className="touch-keyboard-candidate-status">
                {dictionaryState === "loading" ? "词库加载中…"
                  : dictionaryState === "error" ? "词库加载失败，可切换英文输入"
                    : composition ? "暂无候选词" : "点击字母输入拼音"}
              </span>
            )}
          </div>
          <button
            type="button"
            className="touch-keyboard-page-button"
            aria-label="上一页候选词"
            disabled={candidatePage === 0}
            onClick={() => setCandidatePage((page) => Math.max(0, page - 1))}
          ><ChevronLeft size={22} /></button>
          <button
            type="button"
            className="touch-keyboard-page-button"
            aria-label="下一页候选词"
            disabled={candidatePage >= pageCount - 1}
            onClick={() => setCandidatePage((page) => Math.min(pageCount - 1, page + 1))}
          ><ChevronRight size={22} /></button>
        </div>
      )}
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
                  className={`touch-key touch-key-${key}${key === "shift" && shifted ? " active" : ""}${key === "language" ? " active" : ""}`}
                  data-key={key}
                  aria-label={key === "backspace" ? "退格" : key === "shift" ? "大写" : undefined}
                  onClick={() => press(key)}
                >
                  {key === "backspace" ? <Delete size={25} />
                    : key === "shift" ? <ArrowBigUp size={25} />
                      : key === "language" ? <><Languages size={22} /><span>{language === "zh" ? "中 / 英" : "英 / 中"}</span></>
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
