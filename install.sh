#!/usr/bin/env bash
#
# Observer one-line installer (macOS / Linux / WSL):
#   curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
#
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
info()  { echo -e "${GREEN}[observer]${NC} $*"; }
error() { echo -e "${RED}[observer]${NC} $*"; exit 1; }

# --- Prerequisites ---
command -v docker >/dev/null 2>&1 || error "Docker not found. Install Docker Desktop first."
docker info >/dev/null 2>&1       || error "Docker is not running. Start Docker Desktop."

if ! command -v uv >/dev/null 2>&1; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# --- Clone / update ---
INSTALL_DIR="${OBSERVER_DIR:-${HOME}/.observer/app}"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating observer..."
    cd "$INSTALL_DIR" && git pull --ff-only 2>/dev/null || true
else
    info "Installing to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone https://github.com/atmaxmoj/standmeet-observer.git "$INSTALL_DIR" 2>/dev/null || {
        mkdir -p "$INSTALL_DIR"
    }
fi
cd "$INSTALL_DIR"

# --- Setup + start ---
uv run python cli.py setup
uv run python cli.py start

info ""
info "Done! Commands:"
info "  uv run python cli.py status   # Check status"
info "  uv run python cli.py stop     # Stop everything"
info "  uv run python cli.py start    # Start everything"
info "  uv run python cli.py logs     # Docker logs"
