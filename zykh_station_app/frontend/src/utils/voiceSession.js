export const VoicePhase = Object.freeze({
  IDLE: "idle",
  PREPARING: "preparing",
  LISTENING: "listening",
  TRANSCRIBING: "transcribing"
});

export const VoiceEvent = Object.freeze({
  START: "start",
  READY: "ready",
  STOP: "stop",
  COMPLETE: "complete",
  CANCEL: "cancel",
  FAIL: "fail"
});

export function nextVoicePhase(current, event) {
  if (event === VoiceEvent.CANCEL || event === VoiceEvent.FAIL || event === VoiceEvent.COMPLETE) {
    return VoicePhase.IDLE;
  }
  if (event === VoiceEvent.START && current === VoicePhase.IDLE) {
    return VoicePhase.PREPARING;
  }
  if (event === VoiceEvent.READY && current === VoicePhase.PREPARING) {
    return VoicePhase.LISTENING;
  }
  if (event === VoiceEvent.STOP && current === VoicePhase.LISTENING) {
    return VoicePhase.TRANSCRIBING;
  }
  return current;
}

export function isRecordingPhase(phase) {
  return phase === VoicePhase.LISTENING;
}
