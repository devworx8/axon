#!/usr/bin/env bash
# Axon — Desktop Launcher
# Starts the Axon server and opens it in the default browser.

set -euo pipefail

APP_DIR="$HOME/.devbrain"
VENV="$APP_DIR/.venv"
PORT=7734

if [[ ! -d "$VENV" ]]; then
    echo "Axon virtual environment not found at $VENV"
    exit 1
fi

# Check if Axon is already running
if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:$PORT" 2>/dev/null &
    exit 0
fi

# Start the server
cd "$APP_DIR"
"$VENV/bin/python" server.py &
SERVER_PID=$!

# Wait for server to come up (max 20s)
for i in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:$PORT" 2>/dev/null &
        wait "$SERVER_PID" 2>/dev/null
        exit 0
    fi
    sleep 0.5
done

echo "Axon server failed to start within 20 seconds."
kill "$SERVER_PID" 2>/dev/null
exit 1
