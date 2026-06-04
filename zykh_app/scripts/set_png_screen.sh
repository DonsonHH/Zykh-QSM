#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
RUN_DIR="$APP_DIR/runtime"
SCREEN="${1:-home}"
SRC="$APP_DIR/native/screens/$SCREEN.png"
FRAMES="${PNG_UI_FRAMES:-300}"

mkdir -p "$RUN_DIR"

if [ ! -f "$SRC" ]; then
  echo "screen not found: $SCREEN"
  echo "available:"
  ls "$APP_DIR/native/screens" 2>/dev/null | sed 's/\.png$//' || true
  exit 1
fi

i=0
while [ "$i" -lt "$FRAMES" ]; do
  dst=$(printf "$RUN_DIR/native-screen-%05d.png" "$i")
  rm -f "$dst"
  ln "$SRC" "$dst" 2>/dev/null || cp "$SRC" "$dst"
  i=$((i + 1))
done

echo "$FRAMES" > "$RUN_DIR/native-screen-count"
echo "screen set: $SCREEN ($FRAMES frames)"
