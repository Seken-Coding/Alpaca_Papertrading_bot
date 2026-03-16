#!/usr/bin/env bash
# =============================================================================
# Alpaca Paper Trading Bot — VPS Setup Script
# Tested on: Ubuntu 22.04 LTS / 24.04 LTS (IONOS VPS)
#
# Run as root:
#   chmod +x setup.sh
#   sudo ./setup.sh
#
# What this script does:
#   1. Installs Python 3.13 via the deadsnakes PPA
#   2. Creates a dedicated 'trading' system user
#   3. Copies the bot to /opt/trading-bot/
#   4. Creates a Python virtualenv and installs dependencies
#   5. Prompts you to fill in your .env (API keys, automation settings)
#   6. Stops old single-bot services (if present) and installs multi-bot service
# =============================================================================

set -euo pipefail

BOT_DIR="/opt/trading-bot"
BOT_USER="trading"
MULTI_SERVICE="multi-bot"
# Legacy services (stopped and removed during migration)
LEGACY_CEST_SERVICE="trading-bot"
LEGACY_INTRADAY_SERVICE="intraday-bot"
PYTHON_BIN="python3.13"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Must run as root ─────────────────────────────────────────────────────────
[[ "$EUID" -eq 0 ]] || err "Please run as root: sudo ./setup.sh"

# ── Detect if bot source is in the same directory as this script ─────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_SOURCE="$(dirname "$SCRIPT_DIR")"   # parent of deploy/

if [[ ! -f "$BOT_SOURCE/multi_main.py" ]]; then
    err "Could not find multi_main.py in $BOT_SOURCE. Run this script from the deploy/ directory."
fi

info "Bot source directory: $BOT_SOURCE"

# =============================================================================
# 1. System packages & Python 3.13
# =============================================================================
info "Updating package lists ..."
apt-get update -qq

info "Installing system dependencies ..."
apt-get install -y -qq \
    software-properties-common \
    build-essential \
    curl \
    git \
    rsync \
    libssl-dev \
    libffi-dev

# Add deadsnakes PPA for Python 3.13
if ! command -v python3.13 &>/dev/null; then
    info "Adding deadsnakes PPA and installing Python 3.13 ..."
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y -qq python3.13 python3.13-venv python3.13-dev
else
    info "Python 3.13 already installed: $(python3.13 --version)"
fi

# =============================================================================
# 2. Create dedicated system user
# =============================================================================
if id "$BOT_USER" &>/dev/null; then
    warn "User '$BOT_USER' already exists — skipping creation"
else
    info "Creating system user '$BOT_USER' ..."
    useradd --system --shell /usr/sbin/nologin --create-home "$BOT_USER"
fi

# =============================================================================
# 3. Copy bot files to /opt/trading-bot/
# =============================================================================
info "Deploying bot to $BOT_DIR ..."
mkdir -p "$BOT_DIR"

# Copy all project files except virtual environments, git history, logs, and __pycache__
rsync -a --exclude='.git' \
          --exclude='*.pyc' \
          --exclude='__pycache__' \
          --exclude='venv' \
          --exclude='.venv' \
          --exclude='logs' \
          --exclude='.env' \
          "$BOT_SOURCE/" "$BOT_DIR/"

# Create writable runtime directories (shared + per-account)
mkdir -p "$BOT_DIR/logs"
mkdir -p "$BOT_DIR/data"

# Set ownership
chown -R "$BOT_USER:$BOT_USER" "$BOT_DIR"

info "Files deployed to $BOT_DIR"

# =============================================================================
# 4. Python virtual environment
# =============================================================================
VENV="$BOT_DIR/venv"

if [[ -d "$VENV" ]]; then
    warn "Virtualenv already exists at $VENV — reinstalling packages"
else
    info "Creating virtualenv at $VENV ..."
    sudo -u "$BOT_USER" "$PYTHON_BIN" -m venv "$VENV"
fi

info "Installing Python dependencies ..."
sudo -u "$BOT_USER" "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u "$BOT_USER" "$VENV/bin/pip" install --quiet -r "$BOT_DIR/requirements.txt"

info "Installed packages:"
sudo -u "$BOT_USER" "$VENV/bin/pip" list --format=columns

# =============================================================================
# 5. Environment file (.env)
# =============================================================================
ENV_FILE="$BOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    warn ".env already exists at $ENV_FILE — not overwriting"
    warn "Edit it manually to add ACCT1/2/3 API keys if not already set."
else
    info "Creating .env from template ..."
    cp "$BOT_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    chown "$BOT_USER:$BOT_USER" "$ENV_FILE"

    echo ""
    echo "================================================================"
    echo "  ACTION REQUIRED: edit your .env file with real credentials"
    echo "  File location: $ENV_FILE"
    echo ""
    echo "  Multi-account mode requires per-account API keys:"
    echo "    ACCT1_API_KEY=<account 1 API key>"
    echo "    ACCT1_SECRET_KEY=<account 1 secret key>"
    echo "    ACCT2_API_KEY=<account 2 API key>"
    echo "    ACCT2_SECRET_KEY=<account 2 secret key>"
    echo "    ACCT3_API_KEY=<account 3 API key>"
    echo "    ACCT3_SECRET_KEY=<account 3 secret key>"
    echo ""
    echo "  Account mapping (see config/accounts.yaml):"
    echo "    ACCT1 → momentum_aggressive (intraday)"
    echo "    ACCT2 → cest_conservative   (CEST daily)"
    echo "    ACCT3 → cest_aggressive     (CEST daily + pyramiding)"
    echo ""
    echo "  You can also keep ALPACA_API_KEY/SECRET_KEY for standalone"
    echo "  main.py/cest_main.py usage (optional)."
    echo "================================================================"
    echo ""
    read -rp "Press Enter after you have filled in $ENV_FILE ..."
fi

# =============================================================================
# 6. Stop legacy services (if present) and install multi-bot service
# =============================================================================
MULTI_SERVICE_FILE="/etc/systemd/system/${MULTI_SERVICE}.service"

# Stop and disable legacy single-bot services
for SVC in "$LEGACY_CEST_SERVICE" "$LEGACY_INTRADAY_SERVICE"; do
    SVC_FILE="/etc/systemd/system/${SVC}.service"
    if systemctl is-active --quiet "$SVC" 2>/dev/null; then
        info "Stopping legacy service '$SVC' ..."
        systemctl stop "$SVC"
    fi
    if systemctl is-enabled --quiet "$SVC" 2>/dev/null; then
        info "Disabling legacy service '$SVC' ..."
        systemctl disable "$SVC"
    fi
    if [[ -f "$SVC_FILE" ]]; then
        info "Removing legacy service file: $SVC_FILE"
        rm -f "$SVC_FILE"
    fi
done

# Install multi-bot service
info "Installing multi-bot service ..."
cp "$BOT_DIR/deploy/multi-bot.service" "$MULTI_SERVICE_FILE"
chmod 644 "$MULTI_SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$MULTI_SERVICE"

echo ""
info "Multi-bot service installed and enabled for startup on boot."
info "Starting multi-bot service now ..."
systemctl start "$MULTI_SERVICE"

sleep 5   # Give processes a moment to initialise (accounts start with 30s stagger)

echo ""
echo "================================================================"
echo "  DEPLOYMENT COMPLETE — multi-account trading bot active"
echo "================================================================"
echo ""
echo "Service status:"
echo "────────────────────────────────────────"
systemctl status "$MULTI_SERVICE" --no-pager || true
echo ""
echo "Useful commands:"
echo "  systemctl status  $MULTI_SERVICE       # check multi-bot status"
echo "  systemctl stop    $MULTI_SERVICE       # stop all accounts"
echo "  systemctl restart $MULTI_SERVICE       # restart all accounts"
echo "  journalctl -u $MULTI_SERVICE -f        # live log tail"
echo ""
echo "  python multi_main.py --dashboard       # performance leaderboard"
echo "  python multi_main.py --promote         # strategy promotion report"
echo ""
echo "Per-account logs:"
echo "  tail -f $BOT_DIR/logs/momentum_aggressive/app.log"
echo "  tail -f $BOT_DIR/logs/cest_conservative/app.log"
echo "  tail -f $BOT_DIR/logs/cest_aggressive/app.log"
echo ""
echo "Log files are in: $BOT_DIR/logs/<account_id>/"
echo "State files in:   $BOT_DIR/data/<account_id>/"
echo "Account config:   $BOT_DIR/config/accounts.yaml"
echo "Env config:       $ENV_FILE"
