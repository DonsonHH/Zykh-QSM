import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import {
  VoiceEvent,
  VoicePhase,
  isRecordingPhase,
  nextVoicePhase
} from "../src/utils/voiceSession.js";
import { normalizeVoiceTranscript } from "../src/utils/voiceTranscript.js";

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

const root = fileURLToPath(new URL("../", import.meta.url));
const chat = await readFile(`${root}src/components/InquiryChatStep.jsx`, "utf8");
const voiceOverlay = await readFile(`${root}src/components/WxVoiceRecorderOverlay.jsx`, "utf8");
const appCss = await readFile(`${root}src/styles/app.css`, "utf8");
assert.match(chat, /onPointerDown=\{handleHoldStart\}/, "voice recording does not start on press-and-hold");
assert.match(chat, /onPointerUp=\{handleHoldEnd\}/, "voice recording does not stop when the press is released");
assert.match(chat, /transcriptPreview/, "recognized speech is sent without a confirmation preview");
assert.match(voiceOverlay, /确认发送/, "transcript preview has no explicit send action");
assert.match(voiceOverlay, /aria-label="取消发送"/, "transcript preview cannot return to the inquiry before sending");
assert.match(voiceOverlay, /<X size=\{22\} \/>取消发送/, "the cancel-send action is not explicit enough for touch users");
assert.doesNotMatch(voiceOverlay, /onRerecord(Start|End|Cancel)/, "the confirmation view still starts another recording session");
assert.match(chat, /window\.addEventListener\("pointerup"/, "re-rendering the preview can lose the hold-release event");
assert.match(chat, /window\.addEventListener\("pointermove"/, "the recording interaction has no slide-up cancel tracking");
assert.match(chat, /holdStartYRef\.current - event\.clientY >= 84/, "the slide-up cancel threshold changed unexpectedly");
assert.match(chat, /Keyboard/, "the fallback on-screen keyboard entry is missing");
assert.match(chat, /WxVoiceRecorderOverlay/, "press-and-hold does not open the recording surface");
assert.match(voiceOverlay, /wx-voice-waveform/, "the recording surface has no horizontal waveform");
assert.match(voiceOverlay, /wx-voice-hold-surface/, "the recording surface has no bottom hold arc");
assert.match(voiceOverlay, /wx-voice-review-toolbar/, "the transcript preview still uses two competing primary actions");
assert.match(voiceOverlay, /上滑取消/, "the recording interaction does not explain the cancel gesture");
assert.match(voiceOverlay, /WAVE_RATIOS/, "the waveform does not retain the reference's balanced 21-bar profile");
assert.doesNotMatch(voiceOverlay, /wx-voice-diagonal-guide/, "recording still renders the removed decorative motion guide");
assert.doesNotMatch(appCss, /wxVoiceDiagonalGuide|wx-voice-diagonal-guide/, "recording still spends frames on decorative diagonal motion");
assert.doesNotMatch(chat, /voice-overlay-stage|voice-overlay-pulse/, "the rejected circular pulse recorder remains in use");
assert.match(chat, /lang="zh-CN"/, "the keyboard input is not declared as Simplified Chinese");
assert.doesNotMatch(chat, /if \(data\.final\) finishVoice\(data\.text\)/, "ASR final events still auto-send while the user is holding the button");
assert.doesNotMatch(chat, /setTimeout\(\(\) => stopVoice\(true\), 12000\)/, "recording still stops automatically after 12 seconds");
assert.match(
  chat,
  /data\.final && voicePhaseRef\.current === VoicePhase\.TRANSCRIBING/,
  "cloud VAD can still finalize the transcript before the user releases the button"
);
assert.equal(normalizeVoiceTranscript("我有点头晕。"), "我有点头晕", "cloud ASR punctuation was not normalized");
assert.equal(normalizeVoiceTranscript("我咳嗽．．"), "我咳嗽", "full-width trailing punctuation was not normalized");

const voiceBar = chat.slice(chat.indexOf('<div className="chat-voice-bar hold-to-talk">'));
assert.ok(
  voiceBar.indexOf("chat-keyboard-button") < voiceBar.indexOf("voice-chat-button compact"),
  "the press-and-hold button must be the rightmost action"
);
assert.doesNotMatch(chat, /aiSourceLabel/, "technical AI source labels remain in chat bubbles");

const launcher = await readFile(`${root}../scripts/launch_kiosk.sh`, "utf8");
assert.match(launcher, /GTK_IM_MODULE=.*fcitx/, "Chromium is not launched with the Chinese input method module");
assert.match(launcher, /fcitx5-remote[^\n]*-s pinyin/, "the kiosk launcher does not select the Pinyin input method");

console.log("voice session contract: ok");
