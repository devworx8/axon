#!/usr/bin/env bash
# Axon — start the local operator console
# Usage: axon  OR  devbrain  OR  ~/.devbrain/start.sh

set -euo pipefail

DEVBRAIN_DIR="$HOME/.devbrain"
PORT=7734
PIDFILE="$DEVBRAIN_DIR/.pid"
LOGFILE="$DEVBRAIN_DIR/devbrain.log"
HEALTH_URL="http://localhost:$PORT/api/health"
ENV_FILES=("$DEVBRAIN_DIR/.env" "$DEVBRAIN_DIR/.env.local")

health_up() {
  curl -sf "$HEALTH_URL" > /dev/null 2>&1
}

port_pid() {
  ss -ltnp 2>/dev/null | awk -v port=":$PORT" '$4 ~ port {print}' | grep -o 'pid=[0-9]\+' | head -1 | cut -d= -f2
}

is_devbrain_pid() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 1
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "$DEVBRAIN_DIR/server.py"
}

# ── Repair stale state before starting ────────────────────────────
LIVE_PID="$(port_pid || true)"
if health_up && is_devbrain_pid "$LIVE_PID"; then
  echo "$LIVE_PID" > "$PIDFILE"
  echo "Axon is already running (PID $LIVE_PID) → http://localhost:$PORT"
  xdg-open "http://localhost:$PORT" 2>/dev/null || true
  exit 0
fi

# ── Check if already running ──────────────────────────────────────
if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "Axon is already running (PID $PID) → http://localhost:$PORT"
    xdg-open "http://localhost:$PORT" 2>/dev/null || true
    exit 0
  else
    rm -f "$PIDFILE"
  fi
fi

LIVE_PID="$(port_pid || true)"
if [ -n "$LIVE_PID" ]; then
  if is_devbrain_pid "$LIVE_PID"; then
    echo "$LIVE_PID" > "$PIDFILE"
    echo "Axon is already running (PID $LIVE_PID) → http://localhost:$PORT"
    xdg-open "http://localhost:$PORT" 2>/dev/null || true
    exit 0
  fi
  echo "ERROR: Port $PORT is already in use by a different process (PID $LIVE_PID)."
  exit 1
fi

# ── Resolve Python interpreter ────────────────────────────────────
if [ -x "$DEVBRAIN_DIR/.venv/bin/python" ]; then
  PYTHON="$DEVBRAIN_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

# ── Load optional local environment files ─────────────────────────
for ENV_FILE in "${ENV_FILES[@]}"; do
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
  fi
done

# ── Start server ──────────────────────────────────────────────────
echo "✦ Starting Axon on http://localhost:$PORT  ($PYTHON)"

cd "$DEVBRAIN_DIR"
setsid "$PYTHON" "$DEVBRAIN_DIR/server.py" >> "$LOGFILE" 2>&1 < /dev/null &
SERVER_PID=$!
echo $SERVER_PID > "$PIDFILE"

# Wait for server to be ready (up to 8s)
SERVER_READY=0
for i in {1..16}; do
  if health_up; then
    LIVE_PID="$(port_pid || true)"
    if is_devbrain_pid "$LIVE_PID"; then
      echo "$LIVE_PID" > "$PIDFILE"
    fi
    echo "✅ Axon ready (PID ${LIVE_PID:-$SERVER_PID})"
    SERVER_READY=1
    break
  fi
  sleep 0.5
done

if [ "$SERVER_READY" -ne 1 ]; then
  echo "Axon did not pass health checks on $HEALTH_URL"
  tail -n 40 "$LOGFILE" 2>/dev/null || true
  exit 1
fi

# ── Start tunnel (named mode → axon.edudashpro.org.za) ───────────
if TUNNEL_OUTPUT="$("$DEVBRAIN_DIR/tunnel.sh" start 2>&1)"; then
  echo "$TUNNEL_OUTPUT"
else
  echo "$TUNNEL_OUTPUT"
  echo "⚠ Tunnel is not healthy yet. Run $DEVBRAIN_DIR/tunnel.sh doctor for recovery steps."
fi

# Open browser
xdg-open "http://localhost:$PORT" 2>/dev/null || \
  echo "→ Open in browser: http://localhost:$PORT"
echo "🌐 Public PWA: https://axon.edudashpro.org.za"
