from __future__ import annotations

import math

from .. import db


SPEAKER_GAIN_MAX = 255
SPEAKER_GAIN_AUDIBLE_FLOOR = 128
SPEAKER_PERCENT_AUDIBLE_FLOOR = 1
SPEAKER_VOLUME_SCALE_VERSION = "2"
SPEAKER_VOLUME_SCALE_VERSION_KEY = "speaker_volume_scale_version"
LEGACY_SPEAKER_FLOOR_DB = -60

_AUDIBLE_FLOOR_DB = 20 * math.log10(SPEAKER_GAIN_AUDIBLE_FLOOR / SPEAKER_GAIN_MAX)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _round_like_javascript(value: float) -> int:
    return math.floor(value + 0.5)


def speaker_gain_to_percent(gain: int | float) -> int:
    normalized = _clamp(float(gain or 0), 0, SPEAKER_GAIN_MAX)
    if normalized <= 0:
        return 0

    audible_gain = max(SPEAKER_GAIN_AUDIBLE_FLOOR, normalized)
    decibels = 20 * math.log10(audible_gain / SPEAKER_GAIN_MAX)
    position = (decibels - _AUDIBLE_FLOOR_DB) / -_AUDIBLE_FLOOR_DB
    percent = _round_like_javascript(
        SPEAKER_PERCENT_AUDIBLE_FLOOR
        + position * (100 - SPEAKER_PERCENT_AUDIBLE_FLOOR)
    )
    return int(_clamp(percent, SPEAKER_PERCENT_AUDIBLE_FLOOR, 100))


def speaker_percent_to_gain(percent: int | float) -> int:
    normalized = _clamp(float(percent or 0), 0, 100)
    if normalized <= 0:
        return 0

    position = (
        max(SPEAKER_PERCENT_AUDIBLE_FLOOR, normalized)
        - SPEAKER_PERCENT_AUDIBLE_FLOOR
    ) / (100 - SPEAKER_PERCENT_AUDIBLE_FLOOR)
    decibels = _AUDIBLE_FLOOR_DB + position * -_AUDIBLE_FLOOR_DB
    gain = _round_like_javascript(SPEAKER_GAIN_MAX * (10 ** (decibels / 20)))
    return int(_clamp(gain, SPEAKER_GAIN_AUDIBLE_FLOOR, SPEAKER_GAIN_MAX))


def _legacy_gain_to_percent(gain: int) -> int:
    if gain <= 0:
        return 0
    decibels = 20 * math.log10(gain / SPEAKER_GAIN_MAX)
    position = (decibels - LEGACY_SPEAKER_FLOOR_DB) / -LEGACY_SPEAKER_FLOOR_DB
    return int(_clamp(_round_like_javascript(position * 100), 0, 100))


def canonicalize_speaker_gain(gain: int | float) -> int:
    """Accept the new raw scale while preserving old inaudible slider intent."""
    normalized = int(_clamp(_round_like_javascript(float(gain or 0)), 0, SPEAKER_GAIN_MAX))
    if normalized <= 0 or normalized >= SPEAKER_GAIN_AUDIBLE_FLOOR:
        return normalized
    return speaker_percent_to_gain(_legacy_gain_to_percent(normalized))


def get_persisted_speaker_gain(default: int = 230) -> int:
    try:
        stored = int(db.get_setting("speaker_volume", str(default)))
    except ValueError:
        stored = default

    version = db.get_setting(SPEAKER_VOLUME_SCALE_VERSION_KEY, "")
    gain = canonicalize_speaker_gain(stored)
    if stored != gain:
        db.set_setting("speaker_volume", str(gain))
    if version != SPEAKER_VOLUME_SCALE_VERSION:
        db.set_setting(SPEAKER_VOLUME_SCALE_VERSION_KEY, SPEAKER_VOLUME_SCALE_VERSION)
    return gain


def save_persisted_speaker_gain(gain: int | float) -> int:
    canonical = canonicalize_speaker_gain(gain)
    db.set_setting("speaker_volume", str(canonical))
    db.set_setting(SPEAKER_VOLUME_SCALE_VERSION_KEY, SPEAKER_VOLUME_SCALE_VERSION)
    return canonical
