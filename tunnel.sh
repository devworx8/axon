#!/usr/bin/env bash
# Axon — HTTPS tunnel helper
# Usage: ~/.devbrain/tunnel.sh [start|stop|status|url]

DEVBRAIN_DIR="$HOME/.devbrain"
PORT=7734
LOGFILE="$DEVBRAIN_DIR/cloudflared.log"
PIDFILE="$DEVBRAIN_DIR/.tunnel.pid"
CF_BIN="$DEVBRAIN_DIR/cloudflared"
DBFILE="$DEVBRAIN_DIR/devbrain.db"

cmd="${1:-start}"

read_setting() {
  local key="$1"
  if [ -f "$DBFILE" ]; then
    sqlite3 "$DBFILE" "select value from settings where key = '$key' limit 1;" 2>/dev/null | tail -1
  fi
}

STABLE_DOMAIN="$(read_setting stable_domain)"
[ -n "$STABLE_DOMAIN" ] || STABLE_DOMAIN="axon.edudashpro.org.za"
PUBLIC_BASE_URL="$(read_setting public_base_url)"
[ -n "$PUBLIC_BASE_URL" ] || PUBLIC_BASE_URL="https://$STABLE_DOMAIN"
TUNNEL_MODE="$(read_setting tunnel_mode)"
[ -n "$TUNNEL_MODE" ] || TUNNEL_MODE="trycloudflare"
CF_TOKEN="$(read_setting cloudflare_tunnel_token)"

tunnel_pid() {
  pgrep -f "$CF_BIN.*tunnel" | head -1
}

tunnel_url() {
  if [ "$TUNNEL_MODE" = "named" ]; then
    echo "$PUBLIC_BASE_URL"
  else
    grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" 2>/dev/null | tail -1
  fi
}

case "$cmd" in
  start)
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      echo "$LIVE_PID" > "$PIDFILE"
      URL="$(tunnel_url)"
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
    if [ "$TUNNEL_MODE" = "named" ]; then
      if [ -z "$CF_TOKEN" ]; then
        echo "Named tunnel mode is selected, but no Cloudflare tunnel token is saved."
        exit 1
      fi
      nohup "$CF_BIN" --no-autoupdate tunnel run --token "$CF_TOKEN" >> "$LOGFILE" 2>&1 &
    elif [ "$TUNNEL_MODE" = "external" ]; then
      echo "External mode does not start a local tunnel. Use $PUBLIC_BASE_URL"
      exit 0
    else
      nohup "$CF_BIN" tunnel --url "http://localhost:$PORT" --no-autoupdate >> "$LOGFILE" 2>&1 &
    fi
    echo $! > "$PIDFILE"
    echo "Tunnel starting..."
    for i in {1..20}; do
      URL="$(tunnel_url)"
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
      URL="$(tunnel_url)"
      echo "running: $URL"
    else
      rm -f "$PIDFILE"
      echo "stopped"
    fi
    ;;
esac
