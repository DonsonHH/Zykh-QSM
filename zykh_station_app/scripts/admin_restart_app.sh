#!/bin/sh

set -u

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUN_DIR="$ROOT_DIR/data/run"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"

mkdir -p "$RUN_DIR"

stop_pidfile() {
    pidfile=$1
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile" 2>/dev/null || true)
        case "$pid" in
            ''|*[!0-9]*) ;;
            *)
                cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
                command=$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)
                case "$cwd:$command" in
                    "$ROOT_DIR/backend:"*uvicorn*|"$ROOT_DIR/frontend:"*vite*|"$ROOT_DIR/frontend:"*npm*)
                        kill "$pid" 2>/dev/null || true
                        sleep 1
                        kill -9 "$pid" 2>/dev/null || true
                        ;;
                esac
                ;;
        esac
        rm -f "$pidfile"
    fi
}

stop_pidfile "$RUN_DIR/backend.pid"
stop_pidfile "$RUN_DIR/frontend.pid"

for proc in /proc/[0-9]*; do
    pid=${proc#/proc/}
    cwd=$(readlink "$proc/cwd" 2>/dev/null || true)
    case "$cwd" in
        "$ROOT_DIR/backend"|"$ROOT_DIR/frontend")
            command=$(tr '\0' ' ' <"$proc/cmdline" 2>/dev/null || true)
            case "$command" in
                *uvicorn*|*vite*) kill "$pid" 2>/dev/null || true ;;
            esac
            ;;
    esac
done
sleep 1

PYTHON="$ROOT_DIR/backend/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python
fi

cd "$ROOT_DIR/backend" || exit 1
nohup "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >>"$BACKEND_LOG" 2>&1 &
echo $! > "$RUN_DIR/backend.pid"

cd "$ROOT_DIR/frontend" || exit 1
nohup npm run dev -- --host 127.0.0.1 --port 5173 >>"$FRONTEND_LOG" 2>&1 &
echo $! > "$RUN_DIR/frontend.pid"
