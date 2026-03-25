#!/usr/bin/env bash
# Axon — tunnel helper
# Usage: ~/.devbrain/tunnel.sh [start|stop|status|url]

DEVBRAIN_DIR="$HOME/.devbrain"
PORT=7734
LOGFILE="$DEVBRAIN_DIR/cloudflared.log"
PIDFILE="$DEVBRAIN_DIR/.tunnel.pid"
CF_BIN="$DEVBRAIN_DIR/cloudflared"
DBFILE="$DEVBRAIN_DIR/devbrain.db"

cmd="${1:-start}"

read_setting() {
  sqlite3 "$DBFILE" "select value from settings where key='$1' limit 1;" 2>/dev/null
}

tunnel_mode() {
  local mode
  mode="$(read_setting tunnel_mode)"
  if [ -z "$mode" ]; then
    mode="trycloudflare"
  fi
  printf '%s' "$mode"
}

public_base_url() {
  local value
  value="$(read_setting public_base_url)"
  printf '%s' "$value"
}

cloudflare_token() {
  local value
  value="$(read_setting cloudflare_tunnel_token)"
  value="${value#--token }"
  printf '%s' "$value"
}

tunnel_pid() {
  pgrep -f "$CF_BIN.*tunnel" | head -1
}

case "$cmd" in
  start)
    MODE="$(tunnel_mode)"
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      echo "$LIVE_PID" > "$PIDFILE"
      if [ "$MODE" = "named" ]; then
        URL="$(public_base_url)"
      else
        URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" | tail -1)
      fi
      echo "Tunnel already running (PID $LIVE_PID): $URL"
      exit 0
    fi
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        URL="$(tunnel_url)"
        echo "Tunnel already running (PID $PID): $URL"
        exit 0
      fi
      rm -f "$PIDFILE"
    fi
    echo "" > "$LOGFILE"
    if [ "$MODE" = "external" ]; then
      echo "External bridge mode selected — no local tunnel started."
      exit 0
    fi
    if [ "$MODE" = "named" ]; then
      TOKEN="$(cloudflare_token)"
      if [ -z "$TOKEN" ]; then
        echo "Named tunnel token is missing."
        exit 1
      fi
      nohup "$CF_BIN" --no-autoupdate tunnel run --token "$TOKEN" >> "$LOGFILE" 2>&1 &
    else
      nohup "$CF_BIN" tunnel --url "http://localhost:$PORT" --no-autoupdate >> "$LOGFILE" 2>&1 &
    fi
    echo $! > "$PIDFILE"
    echo "Tunnel starting..."
    for i in {1..20}; do
      if [ "$MODE" = "named" ]; then
        URL="$(public_base_url)"
        if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
          echo "✅ Tunnel ready: $URL"
          exit 0
        fi
      else
        URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" 2>/dev/null | tail -1)
      fi
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
    MODE="$(tunnel_mode)"
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      echo "$LIVE_PID" > "$PIDFILE"
      if [ "$MODE" = "named" ]; then
        URL="$(public_base_url)"
      else
        URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" | tail -1)
      fi
      echo "running: $URL"
    else
      rm -f "$PIDFILE"
      echo "stopped"
    fi
    ;;
esac
