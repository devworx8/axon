#!/usr/bin/env bash
# Axon — one-time install script
# Run once: bash ~/.devbrain/install.sh

set -euo pipefail

DEVBRAIN_DIR="$HOME/.devbrain"
BIN_DIR="$HOME/bin"

echo "✦ Installing Axon..."

# ── Python venv + deps ────────────────────────────────────────────
echo "→ Setting up Python virtual environment..."
if [ ! -d "$DEVBRAIN_DIR/.venv" ]; then
  python3 -m venv "$DEVBRAIN_DIR/.venv"
fi

echo "→ Installing Python dependencies..."
"$DEVBRAIN_DIR/.venv/bin/pip" install --quiet --upgrade pip 2>&1 | tail -1
"$DEVBRAIN_DIR/.venv/bin/pip" install --quiet \
     fastapi uvicorn aiosqlite anthropic apscheduler watchdog \
     rich click httpx sse-starlette pydantic python-pptx qrcode \
     Markdown pyotp cryptography bcrypt beautifulsoup4 lxml \
     aiohttp Pillow 2>&1 | tail -3

# ── Make scripts executable ───────────────────────────────────────
chmod +x "$DEVBRAIN_DIR/start.sh"
chmod +x "$DEVBRAIN_DIR/stop.sh"
chmod +x "$DEVBRAIN_DIR/install.sh"

# ── Create CLI wrappers ───────────────────────────────────────────
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/devbrain" <<'ENDCLI'
#!/usr/bin/env bash
# Axon CLI wrapper (legacy command kept for compatibility)

DEVBRAIN_DIR="$HOME/.devbrain"
PORT=7734

case "${1:-start}" in
  start)
    bash "$DEVBRAIN_DIR/start.sh"
    ;;
  stop)
    bash "$DEVBRAIN_DIR/stop.sh"
    ;;
  restart)
    bash "$DEVBRAIN_DIR/stop.sh" 2>/dev/null; sleep 1
    bash "$DEVBRAIN_DIR/start.sh"
    ;;
  status)
    PIDFILE="$DEVBRAIN_DIR/.pid"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
      echo "✅ Axon running (PID $(cat $PIDFILE)) → http://localhost:$PORT"
    else
      echo "🔴 Axon is not running"
    fi
    ;;
  log)
    tail -f "$DEVBRAIN_DIR/devbrain.log"
    ;;
  open)
    xdg-open "http://localhost:$PORT" 2>/dev/null || \
      echo "Open: http://localhost:$PORT"
    ;;
  *)
    echo "Usage: devbrain [start|stop|restart|status|log|open]"
    ;;
esac
ENDCLI
chmod +x "$BIN_DIR/devbrain"

cat > "$BIN_DIR/axon" <<'ENDCLI'
#!/usr/bin/env bash
# Axon CLI wrapper

exec "$HOME/bin/devbrain" "$@"
ENDCLI
chmod +x "$BIN_DIR/axon"

# ── Add ~/bin to PATH if needed ───────────────────────────────────
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"

if ! grep -q 'PATH="$HOME/bin:$PATH"' "$SHELL_RC" 2>/dev/null; then
  echo '' >> "$SHELL_RC"
  echo '# Axon CLI' >> "$SHELL_RC"
  echo 'export PATH="$HOME/bin:$PATH"' >> "$SHELL_RC"
  echo "→ Added ~/bin to PATH in $SHELL_RC"
fi

# ── Create desktop shortcut ───────────────────────────────────────
DESKTOP_FILE="$HOME/.local/share/applications/devbrain.desktop"
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<ENDDESK
[Desktop Entry]
Version=1.0
Name=Axon
Comment=Local AI Operator
Exec=bash $DEVBRAIN_DIR/start.sh
Icon=computer
Terminal=false
Type=Application
Categories=Development;
Keywords=axon;assistant;developer;local-ai;
ENDDESK

echo ""
echo "✅ Axon installed!"
echo ""
echo "Commands:"
echo "  axon              → Start (preferred command)"
echo "  devbrain          → Start (after reloading shell)"
echo "  devbrain status   → Check if running"
echo "  devbrain stop     → Stop server"
echo "  devbrain log      → Tail log"
echo ""
echo "First run: source $SHELL_RC && axon"
echo ""
echo "Then open Settings → Runtime and pick your local model setup."
