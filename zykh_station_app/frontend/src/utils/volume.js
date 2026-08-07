const SPEAKER_GAIN_MAX = 255;
const SPEAKER_GAIN_AUDIBLE_FLOOR = 128;
const SPEAKER_PERCENT_AUDIBLE_FLOOR = 1;
const SPEAKER_AUDIBLE_FLOOR_DB = 20 * Math.log10(SPEAKER_GAIN_AUDIBLE_FLOOR / SPEAKER_GAIN_MAX);

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

export function normalizeSpeakerGain(gain) {
  const normalized = clamp(Math.round(Number(gain) || 0), 0, SPEAKER_GAIN_MAX);
  return normalized === 0 ? 0 : Math.max(SPEAKER_GAIN_AUDIBLE_FLOOR, normalized);
}

export function speakerGainToPercent(gain) {
  const normalized = clamp(Number(gain) || 0, 0, SPEAKER_GAIN_MAX);
  if (normalized <= 0) return 0;

  const audibleGain = Math.max(SPEAKER_GAIN_AUDIBLE_FLOOR, normalized);
  const decibels = 20 * Math.log10(audibleGain / SPEAKER_GAIN_MAX);
  const position = (decibels - SPEAKER_AUDIBLE_FLOOR_DB) / -SPEAKER_AUDIBLE_FLOOR_DB;
  return clamp(
    Math.round(SPEAKER_PERCENT_AUDIBLE_FLOOR + position * (100 - SPEAKER_PERCENT_AUDIBLE_FLOOR)),
    SPEAKER_PERCENT_AUDIBLE_FLOOR,
    100
  );
}

export function speakerPercentToGain(percent) {
  const normalized = clamp(Number(percent) || 0, 0, 100);
  if (normalized <= 0) return 0;

  const position = (Math.max(SPEAKER_PERCENT_AUDIBLE_FLOOR, normalized) - SPEAKER_PERCENT_AUDIBLE_FLOOR)
    / (100 - SPEAKER_PERCENT_AUDIBLE_FLOOR);
  const decibels = SPEAKER_AUDIBLE_FLOOR_DB + position * -SPEAKER_AUDIBLE_FLOOR_DB;
  return clamp(
    Math.round(SPEAKER_GAIN_MAX * (10 ** (decibels / 20))),
    SPEAKER_GAIN_AUDIBLE_FLOOR,
    SPEAKER_GAIN_MAX
  );
}
