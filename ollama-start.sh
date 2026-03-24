#!/usr/bin/env bash
# Axon — Ollama launcher (systemd-aware)
# The Ollama installer creates a systemd service that manages Ollama with GPU support.
# This script defers to the systemd service when available, otherwise starts manually.
#
# One-time setup after fresh Ollama install:
#   sudo mkdir -p /etc/systemd/system/ollama.service.d
#   sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
#   [Service]
#   Environment="OLLAMA_MODELS=/home/edp/.ollama/models"
#   EOF
#   sudo systemctl daemon-reload && sudo systemctl restart ollama

OLLAMA_PID="$HOME/.devbrain/.ollama.pid"
OLLAMA_LOG="$HOME/.devbrain/ollama.log"
OLLAMA_PORT=11434

# --- helpers ---

_systemd_active() {
  systemctl is-active --quiet ollama 2>/dev/null
}

_port_listening() {
  ss -tlnp 2>/dev/null | grep -q ":${OLLAMA_PORT}" || \
  curl -sf "http://127.0.0.1:${OLLAMA_PORT}/api/version" >/dev/null 2>&1
}

_pid_running() {
  [[ -f "$OLLAMA_PID" ]] && kill -0 "$(cat "$OLLAMA_PID")" 2>/dev/null
}

_clear_pidfile() {
  rm -f "$OLLAMA_PID"
}

_gpu_status() {
  if journalctl -u ollama --no-pager -n 50 2>/dev/null | grep -q "library=CUDA\|library=cuda"; then
    echo "GPU (CUDA)"
  elif grep -q "library=CUDA\|library=cuda" "$OLLAMA_LOG" 2>/dev/null; then
    echo "GPU (CUDA)"
  elif _port_listening; then
    # Query running instance
    local info
    info=$(ollama ps 2>/dev/null | tail -n +2 | head -1)
    [[ -n "$info" ]] && echo "running" || echo "idle"
  else
    echo "CPU"
  fi
}

# --- commands ---

case "${1:-start}" in
  start)
    if _systemd_active; then
      _clear_pidfile
      echo "✓ Ollama managed by systemd (GPU active) — use: systemctl status ollama"
      exit 0
    fi
    if _port_listening; then
      if ! _pid_running; then
        _clear_pidfile
      fi
      echo "✓ Ollama already running on port ${OLLAMA_PORT}"
      exit 0
    fi
    if _pid_running; then
      echo "Ollama already running (PID $(cat "$OLLAMA_PID"))"
      exit 0
    fi
    # Kill any orphaned instance
    pkill -f "ollama serve" 2>/dev/null; sleep 0.5
    echo "Starting Ollama (manual mode)..."
    # Do NOT set CUDA_VISIBLE_DEVICES — Ollama warns it breaks GPU discovery
    OLLAMA_MODELS="$HOME/.ollama/models" \
    ollama serve >> "$OLLAMA_LOG" 2>&1 &
    echo $! > "$OLLAMA_PID"
    sleep 2
    if _pid_running; then
      if grep -q "library=CUDA\|library=cuda" "$OLLAMA_LOG" 2>/dev/null; then
        echo "✓ Ollama started with GPU (CUDA) — PID $(cat "$OLLAMA_PID")"
      elif grep -q "library=cpu" "$OLLAMA_LOG" 2>/dev/null; then
        echo "⚠ Ollama started on CPU — reinstall via: curl -fsSL https://ollama.com/install.sh | sh"
      else
        echo "✓ Ollama started — PID $(cat "$OLLAMA_PID")"
      fi
    else
      echo "ERROR: Ollama failed to start. Check: $OLLAMA_LOG"
      tail -5 "$OLLAMA_LOG"
    fi
    ;;

  stop)
    if _systemd_active; then
      _clear_pidfile
      echo "Ollama is managed by systemd. To stop: sudo systemctl stop ollama"
      exit 0
    fi
    if _pid_running; then
      kill "$(cat "$OLLAMA_PID")" && echo "Ollama stopped"
      rm -f "$OLLAMA_PID"
    else
      pkill -f "ollama serve" 2>/dev/null && echo "Ollama stopped" || echo "Ollama not running"
    fi
    ;;

  restart)
    if _systemd_active; then
      echo "Ollama is managed by systemd. To restart: sudo systemctl restart ollama"
      exit 0
    fi
    "$0" stop; sleep 1; "$0" start
    ;;

  status)
    if _systemd_active; then
      _clear_pidfile
      echo "systemd: active"
      journalctl -u ollama --no-pager -n 3 2>/dev/null | grep -E "library=|inference compute" | tail -1
      ollama ps 2>/dev/null
    elif _pid_running; then
      echo "manual: running (PID $(cat "$OLLAMA_PID"))"
      grep -E "library=(CUDA|cuda|cpu)" "$OLLAMA_LOG" 2>/dev/null | tail -1
      ollama ps 2>/dev/null
    elif _port_listening; then
      _clear_pidfile
      echo "running (external process)"
      ollama ps 2>/dev/null
    else
      echo "stopped"
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    ;;
esac
