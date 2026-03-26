#!/usr/bin/env bash
# Axon — stop the local operator console

PIDFILE="$HOME/.devbrain/.pid"
PORT=7734
DEVBRAIN_DIR="$HOME/.devbrain"

port_pid() {
  ss -ltnp 2>/dev/null | awk -v port=":$PORT" '$4 ~ port {print}' | grep -o 'pid=[0-9]\+' | head -1 | cut -d= -f2
}

is_devbrain_pid() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 1
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "$DEVBRAIN_DIR/server.py"
}

stop_pid() {
  local pid="$1"
  kill "$pid" 2>/dev/null || return 1
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    if is_devbrain_pid "$PID"; then
      if stop_pid "$PID"; then
        rm -f "$PIDFILE"
        echo "🛑 Axon stopped (PID $PID)"
        exit 0
      fi
      echo "Axon stop requested, but PID $PID is still alive."
      exit 1
    fi
    echo "PID file points to a non-Axon process; leaving that process untouched."
  fi
  rm -f "$PIDFILE"
fi

LIVE_PID="$(port_pid || true)"
if is_devbrain_pid "$LIVE_PID"; then
  if stop_pid "$LIVE_PID"; then
    rm -f "$PIDFILE"
    echo "🛑 Axon stopped (PID $LIVE_PID)"
  else
    echo "Axon stop requested, but PID $LIVE_PID is still alive."
    exit 1
  fi
else
  echo "Axon is not running"
fi

# Stop tunnel
"$DEVBRAIN_DIR/tunnel.sh" stop 2>/dev/null || true
