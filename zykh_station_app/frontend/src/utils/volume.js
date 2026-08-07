const SPEAKER_GAIN_MAX = 255;
const SPEAKER_FLOOR_DB = -60;

export function speakerGainToPercent(gain) {
  const normalized = Math.max(0, Math.min(SPEAKER_GAIN_MAX, Number(gain) || 0));
  if (normalized <= 0) return 0;
  const decibels = 20 * Math.log10(normalized / SPEAKER_GAIN_MAX);
  return Math.max(0, Math.min(100, Math.round(((decibels - SPEAKER_FLOOR_DB) / -SPEAKER_FLOOR_DB) * 100)));
}

export function speakerPercentToGain(percent) {
  const normalized = Math.max(0, Math.min(100, Number(percent) || 0));
  if (normalized <= 0) return 0;
  const decibels = SPEAKER_FLOOR_DB + (normalized / 100) * -SPEAKER_FLOOR_DB;
  return Math.max(1, Math.min(SPEAKER_GAIN_MAX, Math.round(SPEAKER_GAIN_MAX * (10 ** (decibels / 20)))));
}
