#!/bin/sh
# QSM368ZP-WF mono speaker helper
# Speaker wiring confirmed:
#   J1001 Pin5 / SPKP_OUT -> speaker +
#   J1001 Pin6 / SPKN_OUT -> speaker -
#
# Usage:
#   sh /userdata/medical_assistant/scripts/play_beep.sh
#   sh /userdata/medical_assistant/scripts/play_beep.sh /path/to/file.wav
#   SPK_VOL=205 sh /userdata/medical_assistant/scripts/play_beep.sh

set -u

CARD="${AUDIO_CARD:-0}"
DEVICE="${AUDIO_DEVICE:-hw:0,0}"
SPK_VOL="${SPK_VOL:-205}"
AUDIO_DIR="/userdata/medical_assistant/audio"
DEFAULT_WAV="$AUDIO_DIR/beep_1khz.wav"
WAV_FILE="${1:-$DEFAULT_WAV}"

mkdir -p "$AUDIO_DIR" /userdata/medical_assistant/logs

log() {
    echo "[play_beep] $*"
}

fail() {
    echo "[play_beep][ERROR] $*" >&2
    exit 1
}

log "Set playback path to SPK"
amixer -c "$CARD" cset numid=1 2 >/dev/null 2>&1 || fail "Failed to set Playback Path=SPK"

log "Set SPK volume to $SPK_VOL"
amixer -c "$CARD" cset numid=5 "$SPK_VOL,$SPK_VOL" >/dev/null 2>&1 || fail "Failed to set SPK Volume"

if [ ! -f "$WAV_FILE" ]; then
    if [ "$WAV_FILE" != "$DEFAULT_WAV" ]; then
        fail "WAV file not found: $WAV_FILE"
    fi

    log "Default beep WAV not found, generating $DEFAULT_WAV"

    perl -e '
use strict;
use warnings;

my $sr = 48000;
my $dur = 1.2;
my $n = int($sr * $dur);
my $ch = 2;
my $bps = 16;
my $data = $n * $ch * 2;
my $path = shift @ARGV;

open(my $f, ">:raw", $path) or die $!;

print $f "RIFF";
print $f pack("V", 36 + $data);
print $f "WAVEfmt ";
print $f pack("VvvVVvv", 16, 1, $ch, $sr, $sr * $ch * 2, $ch * 2, $bps);
print $f "data";
print $f pack("V", $data);

for (my $i = 0; $i < $n; $i++) {
    my $env = 1.0;
    my $fade = int($sr * 0.05);
    if ($i < $fade) {
        $env = $i / $fade;
    } elsif ($i > $n - $fade) {
        $env = ($n - $i) / $fade;
    }

    my $v = int(12000 * $env * sin(2 * 3.1415926 * 1000 * $i / $sr));

    # Stereo WAV with same signal on L/R. On QSM368 J1001 Pin5/6 this plays as mono speaker output.
    print $f pack("ss", $v, $v);
}

close($f);
' "$DEFAULT_WAV" || fail "Failed to generate default beep WAV"
fi

if [ ! -f "$WAV_FILE" ]; then
    fail "WAV file still not found: $WAV_FILE"
fi

log "Playing $WAV_FILE via $DEVICE"
aplay -D "$DEVICE" "$WAV_FILE" || fail "aplay failed"

log "Done"
