import assert from "node:assert/strict";
import {
  VoiceEvent,
  VoicePhase,
  isRecordingPhase,
  nextVoicePhase
} from "../src/utils/voiceSession.js";

let phase = VoicePhase.IDLE;
phase = nextVoicePhase(phase, VoiceEvent.START);
assert.equal(phase, VoicePhase.PREPARING, "a tap must enter preparation before recording");
assert.equal(isRecordingPhase(phase), false, "preparation must not display the recording state");

phase = nextVoicePhase(phase, VoiceEvent.READY);
assert.equal(phase, VoicePhase.LISTENING, "only the backend ready event may start recording UI");
assert.equal(isRecordingPhase(phase), true);

phase = nextVoicePhase(phase, VoiceEvent.STOP);
assert.equal(phase, VoicePhase.TRANSCRIBING);
assert.equal(isRecordingPhase(phase), false);

phase = nextVoicePhase(phase, VoiceEvent.COMPLETE);
assert.equal(phase, VoicePhase.IDLE);

assert.equal(nextVoicePhase(VoicePhase.PREPARING, VoiceEvent.CANCEL), VoicePhase.IDLE);
assert.equal(nextVoicePhase(VoicePhase.LISTENING, VoiceEvent.FAIL), VoicePhase.IDLE);
assert.equal(nextVoicePhase(VoicePhase.IDLE, VoiceEvent.READY), VoicePhase.IDLE, "a late ready event must be ignored");

console.log("voice session contract: ok");
