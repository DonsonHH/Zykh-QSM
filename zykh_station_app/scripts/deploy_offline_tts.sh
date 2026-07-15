#!/usr/bin/env bash

if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ARCHIVE="${1:-$REPO_ROOT/智药康护-QSM368ZP离线TTS部署包(1).zip}"
ADB_BIN="${ADB_BIN:-adb}"
INSTALL_GATEWAY="${INSTALL_GATEWAY:-0}"
PLAYBACK_TEST="${PLAYBACK_TEST:-0}"

for command in "$ADB_BIN" unzip sha256sum base64; do
    command -v "$command" >/dev/null 2>&1 || {
        printf '[offline-tts] missing command: %s\n' "$command" >&2
        exit 1
    }
done
test -f "$ARCHIVE" || {
    printf '[offline-tts] archive not found: %s\n' "$ARCHIVE" >&2
    exit 1
}

mapfile -t devices < <("$ADB_BIN" devices | awk 'NR > 1 && $2 == "device" {print $1}')
if [[ -n "${ADB_SERIAL:-}" ]]; then
    adb=("$ADB_BIN" -s "$ADB_SERIAL")
elif [[ ${#devices[@]} -eq 1 ]]; then
    adb=("$ADB_BIN" -s "${devices[0]}")
else
    printf '[offline-tts] expected one ADB device, found %s; set ADB_SERIAL when needed.\n' "${#devices[@]}" >&2
    exit 1
fi

tmpdir="$(mktemp -d /tmp/zykh-offline-tts-deploy.XXXXXX)"
trap 'rm -rf "$tmpdir"' EXIT
unzip -q "$ARCHIVE" 'payload/zykh_voice/*' -d "$tmpdir"
voice_payload="$tmpdir/payload/zykh_voice"

required=(
    runtime/bin/sherpa-onnx-offline-tts
    runtime/lib/libonnxruntime.so
    runtime/lib/libsherpa-onnx-c-api.so
    runtime/lib/libsherpa-onnx-cxx-api.so
    models/tts/zh_CN-xiao_ya-medium.onnx
    models/tts/lexicon.txt
    models/tts/tokens.txt
    models/tts/phone.fst
    models/tts/date.fst
    models/tts/number.fst
)
for relative in "${required[@]}"; do
    test -s "$voice_payload/$relative" || {
        printf '[offline-tts] payload file missing: %s\n' "$relative" >&2
        exit 1
    }
done

architecture="$(${adb[@]} shell uname -m | tr -d '\r')"
[[ "$architecture" == "aarch64" || "$architecture" == "arm64" ]] || {
    printf '[offline-tts] unsupported board architecture: %s\n' "$architecture" >&2
    exit 1
}

free_kb="$(${adb[@]} shell "df -Pk /userdata | awk 'NR==2 {print \$4}'" | tr -d '\r')"
payload_kb="$(du -sk "$voice_payload" | awk '{print $1}')"
required_kb=$((payload_kb + 30720))
[[ "$free_kb" =~ ^[0-9]+$ && "$free_kb" -ge "$required_kb" ]] || {
    printf '[offline-tts] insufficient /userdata space: need %s KiB, available %s KiB.\n' "$required_kb" "$free_kb" >&2
    exit 1
}

printf '[offline-tts] uploading %s MiB to QSM...\n' "$((payload_kb / 1024))"
"${adb[@]}" shell 'mkdir -p /userdata/zykh_voice /userdata/zykh_app/scripts /userdata/zykh_app/data/audio'
"${adb[@]}" push "$voice_payload/." /userdata/zykh_voice/ >/dev/null
"${adb[@]}" push "$REPO_ROOT/zykh_app/scripts/offline_tts.sh" /userdata/zykh_app/scripts/offline_tts.sh >/dev/null
"${adb[@]}" shell 'chmod 755 /userdata/zykh_voice/runtime/bin/* /userdata/zykh_app/scripts/offline_tts.sh'

for relative in runtime/bin/sherpa-onnx-offline-tts runtime/lib/libonnxruntime.so models/tts/zh_CN-xiao_ya-medium.onnx models/tts/lexicon.txt; do
    local_hash="$(sha256sum "$voice_payload/$relative" | awk '{print $1}')"
    remote_hash="$(${adb[@]} shell "sha256sum /userdata/zykh_voice/$relative | awk '{print \$1}'" | tr -d '\r')"
    [[ "$local_hash" == "$remote_hash" ]] || {
        printf '[offline-tts] checksum mismatch: %s\n' "$relative" >&2
        exit 1
    }
done

if [[ "$INSTALL_GATEWAY" == "1" ]]; then
    stamp="$(date +%Y%m%d-%H%M%S)"
    "${adb[@]}" shell "mkdir -p /userdata/zykh-backups/$stamp && cp -a /userdata/zykh_app/server.pl /userdata/zykh-backups/$stamp/server.pl"
    "${adb[@]}" push "$REPO_ROOT/zykh_app/server.pl" /userdata/zykh_app/server.pl >/dev/null
    "${adb[@]}" shell 'chmod 755 /userdata/zykh_app/server.pl && perl -c /userdata/zykh_app/server.pl'
    "${adb[@]}" shell '/userdata/zykh_app/scripts/start_station_gateway.sh'
fi

test_text='智药康护离线语音播报测试成功。'
test_b64="$(printf '%s' "$test_text" | base64 -w 0)"
printf '[offline-tts] generating a test wave without network access...\n'
"${adb[@]}" shell "text=\$(printf '%s' '$test_b64' | base64 -d); TTS_LENGTH_SCALE=0.82 /userdata/zykh_app/scripts/offline_tts.sh \"\$text\" /userdata/zykh_app/data/audio/offline-tts-deploy-test.wav"
"${adb[@]}" shell 'test -s /userdata/zykh_app/data/audio/offline-tts-deploy-test.wav && ls -lh /userdata/zykh_app/data/audio/offline-tts-deploy-test.wav'

if [[ "$PLAYBACK_TEST" == "1" ]]; then
    "${adb[@]}" shell 'amixer -q -c 0 cset numid=1 2; amixer -q -c 0 cset numid=5 230,230; aplay -q -D plughw:0,0 /userdata/zykh_app/data/audio/offline-tts-deploy-test.wav'
fi

printf '[offline-tts] deployment complete.\n'
