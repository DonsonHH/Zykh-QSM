#!/bin/sh

set -u

APP_DIR=/userdata/zykh_app
cd "$APP_DIR" || exit 1

pidof perl >/dev/null 2>&1 && kill $(pidof perl) 2>/dev/null
sleep 1

TZ="${TZ:-CST-8}" AI_MODEL="${AI_MODEL:-deepseek-v4-flash}" perl server.pl --daemon \
  > "$APP_DIR/server.log" 2>&1 < /dev/null

sleep 1
if pidof perl >/dev/null 2>&1; then
  echo "ZYKH server started: $(pidof perl)"
  echo "Open: http://127.0.0.1:8080/"
else
  echo "ZYKH server failed, see $APP_DIR/server.log"
  tail -80 "$APP_DIR/server.log" 2>/dev/null
  exit 1
fi
