#!/usr/bin/env bash
# Axon — HTTPS tunnel helper
# Usage: ~/.devbrain/tunnel.sh [start|stop|status|url|doctor]

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
LOCAL_HEALTH_URL="http://localhost:$PORT/api/health"
PUBLIC_HEALTH_URL="$PUBLIC_BASE_URL/api/health"

tunnel_pid() {
  pgrep -f "$CF_BIN.*tunnel" | head -1
}

local_health_up() {
  curl -fsS --max-time 3 "$LOCAL_HEALTH_URL" >/dev/null 2>&1
}

public_health_up() {
  curl -fsS --max-time 5 "$PUBLIC_HEALTH_URL" >/dev/null 2>&1
}

tunnel_running() {
  local live_pid
  live_pid="$(tunnel_pid || true)"
  [ -n "$live_pid" ] && kill -0 "$live_pid" 2>/dev/null
}

tunnel_url() {
  if [ "$TUNNEL_MODE" = "named" ]; then
    echo "$PUBLIC_BASE_URL"
  else
    grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" 2>/dev/null | tail -1
  fi
}

wait_for_tunnel_ready() {
  for _ in {1..20}; do
    if [ "$TUNNEL_MODE" = "named" ]; then
      if tunnel_running && public_health_up; then
        return 0
      fi
    else
      URL="$(tunnel_url)"
      if [ -n "$URL" ]; then
        return 0
      fi
    fi
    sleep 0.5
  done
  return 1
}

case "$cmd" in
  start)
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      if [ "$TUNNEL_MODE" = "named" ] && ! public_health_up; then
        echo "Tunnel process exists but the public host is unhealthy. Restarting tunnel..."
        kill "$LIVE_PID" 2>/dev/null || true
        rm -f "$PIDFILE"
        sleep 1
        LIVE_PID=""
      fi
    fi
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
    if wait_for_tunnel_ready; then
      URL="$(tunnel_url)"
      echo "✅ Tunnel ready: $URL"
      exit 0
    fi
    echo "Tunnel failed to become healthy. Check $LOGFILE or run $DEVBRAIN_DIR/tunnel.sh doctor"
    exit 1
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
    if [ "$TUNNEL_MODE" = "external" ]; then
      echo "external: $PUBLIC_BASE_URL"
      exit 0
    fi
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      echo "$LIVE_PID" > "$PIDFILE"
      URL="$(tunnel_url)"
      if [ "$TUNNEL_MODE" = "named" ] && ! public_health_up; then
        echo "degraded: $URL"
        exit 1
      fi
      echo "running: $URL"
    else
      rm -f "$PIDFILE"
      echo "stopped"
      exit 1
    fi
    ;;
  doctor)
    if local_health_up; then
      echo "local_server: ok ($LOCAL_HEALTH_URL)"
    else
      echo "local_server: down ($LOCAL_HEALTH_URL)"
    fi
    LIVE_PID="$(tunnel_pid || true)"
    if [ -n "$LIVE_PID" ] && kill -0 "$LIVE_PID" 2>/dev/null; then
      echo "tunnel_process: running (PID $LIVE_PID)"
    else
      echo "tunnel_process: stopped"
    fi
    if [ "$TUNNEL_MODE" = "named" ]; then
      if public_health_up; then
        echo "public_host: ok ($PUBLIC_BASE_URL)"
      else
        echo "public_host: down ($PUBLIC_BASE_URL)"
      fi
    else
      echo "public_host: $TUNNEL_MODE ($PUBLIC_BASE_URL)"
    fi
    if ! local_health_up; then
      echo "recovery: run $DEVBRAIN_DIR/start.sh"
    elif [ "$TUNNEL_MODE" = "named" ] && ! tunnel_running; then
      echo "recovery: run $DEVBRAIN_DIR/tunnel.sh start"
    elif [ "$TUNNEL_MODE" = "named" ] && ! public_health_up; then
      echo "recovery: run $DEVBRAIN_DIR/tunnel.sh start"
    else
      echo "recovery: none"
    fi
    ;;
esac
