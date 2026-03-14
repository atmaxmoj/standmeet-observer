#!/usr/bin/env bash
set -euo pipefail

OS="$(uname -s)"
echo "==> Detected OS: $OS"

# --- Install screenpipe ---
if command -v screenpipe >/dev/null 2>&1; then
    echo "==> screenpipe already installed: $(screenpipe --version 2>/dev/null || echo 'unknown')"
else
    echo "==> Installing screenpipe..."
    case "$OS" in
        Darwin)
            if ! command -v brew >/dev/null 2>&1; then
                echo "ERROR: brew not found. Install Homebrew first: https://brew.sh"
                exit 1
            fi
            brew install screenpipe
            ;;
        Linux)
            curl -fsSL https://screenpi.pe/install.sh | bash
            ;;
        *)
            echo "ERROR: Unsupported OS: $OS"
            echo "Install screenpipe manually: https://github.com/mediar-ai/screenpipe"
            exit 1
            ;;
    esac
    echo "==> screenpipe installed"
fi

# --- Determine screenpipe data path ---
case "$OS" in
    Darwin)
        SP_DATA="${HOME}/.screenpipe"
        ;;
    Linux)
        SP_DATA="${XDG_DATA_HOME:-${HOME}/.local/share}/screenpipe"
        ;;
esac

# --- Start screenpipe ---
if pgrep -x screenpipe >/dev/null 2>&1; then
    echo "==> screenpipe already running (pid $(pgrep -x screenpipe))"
else
    echo "==> Starting screenpipe..."
    mkdir -p "$SP_DATA"
    screenpipe > /tmp/screenpipe.log 2>&1 &
    echo "==> Waiting for screenpipe DB..."
    for i in $(seq 1 30); do
        [ -f "$SP_DATA/db.sqlite" ] && break
        sleep 2
        printf "."
    done
    echo ""
fi

if [ -f "$SP_DATA/db.sqlite" ]; then
    echo "==> screenpipe DB ready at $SP_DATA/db.sqlite"
else
    echo "==> WARNING: screenpipe DB not found yet"
    case "$OS" in
        Darwin)
            echo "==> Grant permission: System Settings > Privacy & Security > Screen Recording > screenpipe"
            ;;
        Linux)
            echo "==> Make sure screenpipe has screen capture access"
            ;;
    esac
fi

# --- Check .env ---
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "==> ERROR: .env not found. Copy .env.example and set ANTHROPIC_API_KEY"
    echo "   cp .env.example .env && echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env"
    exit 1
fi

# --- Write screenpipe path into env for docker ---
export SCREENPIPE_HOST_PATH="$SP_DATA"

# --- Start bisimulator ---
echo "==> Building and starting bisimulator..."
cd "$SCRIPT_DIR"
docker compose up --build -d

echo ""
echo "==> Done!"
echo "    API:    http://localhost:5001"
echo "    Logs:   docker compose logs -f"
echo "    Status: curl http://localhost:5001/engine/status"
