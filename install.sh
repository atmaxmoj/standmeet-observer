#!/usr/bin/env bash
#
# Bisimulator one-line installer:
#   curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
#
# Prerequisites: Docker must be running.
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[bisimulator]${NC} $*"; }
warn()  { echo -e "${YELLOW}[bisimulator]${NC} $*"; }
error() { echo -e "${RED}[bisimulator]${NC} $*"; exit 1; }

OS="$(uname -s)"
info "Detected OS: $OS"

# --- Check Docker ---
if ! command -v docker >/dev/null 2>&1; then
    error "Docker not found. Install Docker Desktop first: https://www.docker.com/products/docker-desktop/"
fi
if ! docker info >/dev/null 2>&1; then
    error "Docker is not running. Start Docker Desktop and try again."
fi
info "Docker is running"

# --- Install screenpipe ---
if command -v screenpipe >/dev/null 2>&1; then
    info "screenpipe already installed"
else
    info "Installing screenpipe..."
    case "$OS" in
        Darwin)
            if ! command -v brew >/dev/null 2>&1; then
                error "Homebrew not found. Install it first: https://brew.sh"
            fi
            brew install screenpipe
            ;;
        Linux)
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL https://screenpi.pe/install.sh | bash
            else
                error "curl not found. Install curl and try again."
            fi
            ;;
        *)
            error "Unsupported OS: $OS. Install screenpipe manually: https://github.com/mediar-ai/screenpipe"
            ;;
    esac
    info "screenpipe installed"
fi

# --- Start screenpipe ---
if pgrep -x screenpipe >/dev/null 2>&1; then
    info "screenpipe already running"
else
    info "Starting screenpipe..."
    mkdir -p "${HOME}/.screenpipe"
    screenpipe > /tmp/screenpipe.log 2>&1 &
    info "Waiting for screenpipe to initialize..."
    for i in $(seq 1 30); do
        [ -f "${HOME}/.screenpipe/db.sqlite" ] && break
        sleep 2
        printf "."
    done
    echo ""
fi

case "$OS" in
    Darwin) SP_DATA="${HOME}/.screenpipe" ;;
    Linux)  SP_DATA="${XDG_DATA_HOME:-${HOME}/.local/share}/screenpipe" ;;
esac

if [ -f "$SP_DATA/db.sqlite" ]; then
    info "screenpipe DB ready"
else
    warn "screenpipe DB not found yet."
    case "$OS" in
        Darwin) warn "You may need to grant screen recording permission:" ;
                warn "  System Settings > Privacy & Security > Screen Recording > screenpipe" ;;
        Linux)  warn "Make sure screenpipe has screen capture access." ;;
    esac
fi

# --- Clone or update bisimulator ---
INSTALL_DIR="${BISIMULATOR_DIR:-${HOME}/.bisimulator}"

if [ -d "$INSTALL_DIR" ]; then
    info "Updating bisimulator in $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull --ff-only 2>/dev/null || true
else
    info "Installing bisimulator to $INSTALL_DIR..."
    git clone https://github.com/user/bisimulator.git "$INSTALL_DIR" 2>/dev/null || {
        # If no remote repo yet, just create dir structure
        mkdir -p "$INSTALL_DIR"
        warn "No remote repo found — copying local files"
    }
fi

# --- API key ---
if [ -f "$INSTALL_DIR/.env" ]; then
    info "Using existing .env"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" > "$INSTALL_DIR/.env"
    info "Created .env from environment variable"
else
    warn "No API key found!"
    echo ""
    echo "  Set your Anthropic API key:"
    echo "    export ANTHROPIC_API_KEY=sk-ant-..."
    echo "    # then re-run this script"
    echo ""
    echo "  Or create manually:"
    echo "    echo 'ANTHROPIC_API_KEY=sk-ant-...' > $INSTALL_DIR/.env"
    echo ""
    error "ANTHROPIC_API_KEY is required"
fi

# --- Start ---
cd "$INSTALL_DIR"
export SCREENPIPE_HOST_PATH="$SP_DATA"

info "Building and starting bisimulator..."
docker compose up --build -d

echo ""
info "========================================="
info "  Bisimulator is running!"
info "========================================="
info ""
info "  API:     http://localhost:5001"
info "  Status:  curl http://localhost:5001/engine/status"
info "  Logs:    cd $INSTALL_DIR && docker compose logs -f"
info ""
info "  Stop:    cd $INSTALL_DIR && docker compose down"
info "  Restart: cd $INSTALL_DIR && docker compose up -d"
info ""
