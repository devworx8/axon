#!/usr/bin/env bash
# Axon — HTTPS tunnel via cloudflared (no account needed)
# Usage: ~/.devbrain/tunnel.sh [start|stop|status|url]

DEVBRAIN_DIR="$HOME/.devbrain"
PORT=7734
LOGFILE="$DEVBRAIN_DIR/cloudflared.log"
PIDFILE="$DEVBRAIN_DIR/.tunnel.pid"
CF_BIN="$DEVBRAIN_DIR/cloudflared"

cmd="${1:-start}"

tunnel_pid() {
  pgrep -f "$CF_BIN tunnel --url http://localhost:$PORT" | head -1
}

case "$cmd" in
  start)
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      echo "$LIVE_PID" > "$PIDFILE"
      URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" | tail -1)
      echo "Tunnel already running (PID $LIVE_PID): $URL"
      exit 0
    fi
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" | tail -1)
        echo "Tunnel already running (PID $PID): $URL"
        exit 0
      fi
      rm -f "$PIDFILE"
    fi
    echo "" > "$LOGFILE"
    nohup "$CF_BIN" tunnel --url "http://localhost:$PORT" --no-autoupdate >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Tunnel starting..."
    for i in {1..20}; do
      URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" 2>/dev/null | tail -1)
      if [ -n "$URL" ]; then
        echo "✅ Tunnel ready: $URL"
        exit 0
      fi
      sleep 0.5
    done
    echo "Tunnel started but URL not yet available. Check $LOGFILE"
    ;;
  stop)
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      kill "$LIVE_PID" 2>/dev/null && echo "Tunnel stopped." || echo "Already stopped."
      rm -f "$PIDFILE"
      echo "" > "$LOGFILE"
    else
      rm -f "$PIDFILE"
      echo "No tunnel running."
    fi
    ;;
  status|url)
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      echo "$LIVE_PID" > "$PIDFILE"
      URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" | tail -1)
      echo "running: $URL"
    else
      rm -f "$PIDFILE"
      echo "stopped"
    fi
    ;;
esac
