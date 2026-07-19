import React from "react";
import { MessageCircle, Mic, Send, X } from "lucide-react";

const WAVE_RATIOS = [
  0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.5,
  0.3, 0.5, 0.8, 1, 0.8, 0.5, 0.3,
  0.5, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2
];

export function WxVoiceRecorderOverlay({
  phase,
  message,
  transcript,
  cancelGesture,
  sending,
  onClose,
  onRerecordStart,
  onRerecordEnd,
  onRerecordCancel,
  onSend
}) {
  const reviewing = Boolean(transcript);
  const listening = phase === "listening";
  const preparing = phase === "preparing";
  const processing = phase === "processing";

  return (
    <div
      className={`wx-voice-overlay ${phase} ${cancelGesture ? "cancelling" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label={reviewing ? "核对语音文字" : "语音输入"}
    >
      <button type="button" className="wx-voice-close" onClick={onClose} aria-label="关闭语音输入">
        <X size={25} />
      </button>

      {reviewing ? (
        <section className="wx-voice-review-card">
          <span className="wx-voice-review-icon" aria-hidden="true"><MessageCircle size={30} /></span>
          <div className="wx-voice-review-copy">
            <span>请确认我听到的内容</span>
            <h3>{transcript}</h3>
          </div>
          <div className="wx-voice-review-toolbar">
            <button
              type="button"
              className="wx-voice-rerecord"
              aria-label="重新录音"
              title="重新录音"
              onPointerDown={onRerecordStart}
              onPointerUp={onRerecordEnd}
              onPointerCancel={onRerecordCancel}
              onContextMenu={(event) => event.preventDefault()}
            >
              <Mic size={24} />
            </button>
            <button type="button" className="wx-voice-send" onClick={onSend} disabled={sending}>
              <Send size={22} />确认发送
            </button>
          </div>
        </section>
      ) : (
        <>
          <section className="wx-voice-wave-card" aria-live="polite">
            <div className="wx-voice-waveform" aria-hidden="true">
              {WAVE_RATIOS.map((ratio, index) => (
                <i
                  key={`${ratio}-${index}`}
                  className="wx-voice-wave-bar"
                  style={{
                    "--wave-ratio": ratio,
                    "--wave-order": index,
                    "--wave-height": `${Math.round(8 + ratio * 48)}px`
                  }}
                />
              ))}
            </div>
            <strong>
              {cancelGesture
                ? "松开取消"
                : preparing
                  ? "正在准备"
                  : processing
                    ? "正在识别"
                    : listening
                      ? "正在听"
                      : "语音输入"}
            </strong>
          </section>

          <p className="wx-voice-instruction">
            {cancelGesture
              ? "保持上滑位置，松开即可取消"
              : preparing
                ? "请继续按住，准备好后再说话"
                : processing
                  ? "正在把语音整理成文字"
                  : "松开完成 · 上滑取消"}
          </p>

          <div className="wx-voice-hold-surface" aria-hidden="true">
            <span className="wx-voice-mic"><Mic size={39} strokeWidth={2.1} /></span>
            <strong>{cancelGesture ? "取消录音" : listening ? "按住说话" : processing ? "请稍候" : "保持按住"}</strong>
            <small>{cancelGesture ? "松开后不会发送" : message}</small>
          </div>
        </>
      )}
    </div>
  );
}
