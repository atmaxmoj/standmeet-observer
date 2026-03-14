#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OS="$(uname -s)"
echo "==> Detected OS: $OS"

# --- Check prerequisites ---
if ! command -v docker >/dev/null 2>&1; then
    echo "==> ERROR: Docker not found. Install Docker Desktop first."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "==> ERROR: Docker is not running. Start Docker Desktop and try again."
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "==> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# --- Check .env ---
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "==> ERROR: .env not found. Copy .env.example and set ANTHROPIC_API_KEY"
    echo "   cp .env.example .env"
    exit 1
fi

mkdir -p ~/.bisimulator

# --- Determine platform extras for capture daemon ---
case "$OS" in
    Darwin)  CAPTURE_EXTRA="macos" ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
             CAPTURE_EXTRA="windows" ;;
    *)
        echo "==> WARNING: Unsupported OS for screen capture: $OS"
        echo "==> Skipping capture daemon."
        CAPTURE_EXTRA=""
        ;;
esac

# --- Install + start capture daemon ---
if [ -n "$CAPTURE_EXTRA" ]; then
    echo "==> Installing capture daemon dependencies (platform: $CAPTURE_EXTRA)..."
    cd "$SCRIPT_DIR/capture"
    uv sync --extra "$CAPTURE_EXTRA"

    if pgrep -f "python -m capture" >/dev/null 2>&1; then
        echo "==> Capture daemon already running"
    else
        echo "==> Starting capture daemon..."
        uv run python -m capture > /tmp/bisimulator-capture.log 2>&1 &
        sleep 2
        if pgrep -f "python -m capture" >/dev/null 2>&1; then
            echo "==> Capture daemon started (pid $(pgrep -f 'python -m capture'))"
        else
            echo "==> WARNING: Capture daemon failed to start. Check /tmp/bisimulator-capture.log"
            tail -20 /tmp/bisimulator-capture.log 2>/dev/null
            echo "==> Continuing without screen capture..."
        fi
    fi
fi

# --- Install + start audio daemon (cross-platform) ---
echo "==> Installing audio daemon dependencies..."
cd "$SCRIPT_DIR/audio"
uv sync

if pgrep -f "python -m audio" >/dev/null 2>&1; then
    echo "==> Audio daemon already running"
else
    echo "==> Starting audio daemon..."
    uv run python -m audio > /tmp/bisimulator-audio.log 2>&1 &
    sleep 3
    if pgrep -f "python -m audio" >/dev/null 2>&1; then
        echo "==> Audio daemon started (pid $(pgrep -f 'python -m audio'))"
    else
        echo "==> WARNING: Audio daemon failed to start. Check /tmp/bisimulator-audio.log"
        tail -20 /tmp/bisimulator-audio.log 2>/dev/null
        echo "==> Continuing without audio capture..."
    fi
fi

# --- Start bisimulator engine ---
echo "==> Building and starting bisimulator engine..."
cd "$SCRIPT_DIR"
docker compose up --build -d

echo ""
echo "==> Done!"
echo "    API:      http://localhost:5001"
echo "    Usage:    http://localhost:5001/engine/usage"
echo "    Logs:     docker compose logs -f"
echo "    Capture:  tail -f /tmp/bisimulator-capture.log"
echo "    Audio:    tail -f /tmp/bisimulator-audio.log"
echo "    Status:   make status"
