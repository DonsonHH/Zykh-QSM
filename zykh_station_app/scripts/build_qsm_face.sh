#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ]; then
  printf 'Usage: %s FACE_BUNDLE OUTPUT\n' "$0" >&2
  exit 2
fi

FACE_BUNDLE="$1"
OUTPUT="$2"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
SOURCE="$PROJECT_ROOT/qsm_gateway/src/qsm_face.c"
INCLUDE_DIR="$PROJECT_ROOT/qsm_gateway/include"
COMPILER="${QSM_FACE_CC:-aarch64-linux-gnu-gcc}"
TEMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

[ -f "$FACE_BUNDLE" ] || { printf 'Face bundle not found: %s\n' "$FACE_BUNDLE" >&2; exit 1; }
[ -f "$SOURCE" ] || { printf 'Face source not found: %s\n' "$SOURCE" >&2; exit 1; }
command -v "$COMPILER" >/dev/null 2>&1 || {
  printf 'AArch64 compiler not found: %s\n' "$COMPILER" >&2
  exit 1
}

unzip -p "$FACE_BUNDLE" board/lib/libInspireFace.so >"$TEMP_DIR/libInspireFace.so"
[ -s "$TEMP_DIR/libInspireFace.so" ] || {
  printf 'Face bundle is missing board/lib/libInspireFace.so\n' >&2
  exit 1
}
unzip -p "$FACE_BUNDLE" board/lib/librknnrt.so >"$TEMP_DIR/librknnrt.so"
[ -s "$TEMP_DIR/librknnrt.so" ] || {
  printf 'Face bundle is missing board/lib/librknnrt.so\n' >&2
  exit 1
}

mkdir -p "$(dirname -- "$OUTPUT")"
"$COMPILER" \
  -std=c11 -O3 -Wall -Wextra -no-pie \
  -I "$INCLUDE_DIR" \
  "$SOURCE" \
  -L "$TEMP_DIR" \
  -Wl,-rpath-link,"$TEMP_DIR" \
  -Wl,-rpath,'$ORIGIN/lib' \
  -lInspireFace -lrknnrt \
  -o "$OUTPUT"
chmod 755 "$OUTPUT"
printf 'Built QSM face runtime: %s\n' "$OUTPUT"
