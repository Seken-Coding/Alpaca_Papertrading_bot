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
#   6. Installs and enables the systemd service
# =============================================================================

set -euo pipefail

BOT_DIR="/opt/trading-bot"
BOT_USER="trading"
CEST_SERVICE="trading-bot"
INTRADAY_SERVICE="intraday-bot"
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

if [[ ! -f "$BOT_SOURCE/cest_main.py" ]]; then
    err "Could not find cest_main.py in $BOT_SOURCE. Run this script from the deploy/ directory."
fi
if [[ ! -f "$BOT_SOURCE/main.py" ]]; then
    err "Could not find main.py in $BOT_SOURCE. Run this script from the deploy/ directory."
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

# Create writable runtime directories
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
    warn "Edit it manually if you need to update credentials."
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
    echo "  Minimum required settings:"
    echo "    ALPACA_API_KEY=<your paper trading API key>"
    echo "    ALPACA_SECRET_KEY=<your paper trading secret key>"
    echo ""
    echo "  For automatic daily trading also set:"
    echo "    AUTO_EXECUTE=true"
    echo "    ALPACA_PAPER=true   (keep this true until you're confident)"
    echo "================================================================"
    echo ""
    read -rp "Press Enter after you have filled in $ENV_FILE ..."

    # Validate that the required keys are not still placeholders
    if grep -q "your_api_key_here" "$ENV_FILE"; then
        warn "ALPACA_API_KEY still contains placeholder — the bot will not start until you edit $ENV_FILE"
    fi
fi

# =============================================================================
# 6. Systemd services (both CEST daily bot and intraday scanner)
# =============================================================================
CEST_SERVICE_FILE="/etc/systemd/system/${CEST_SERVICE}.service"
INTRADAY_SERVICE_FILE="/etc/systemd/system/${INTRADAY_SERVICE}.service"

info "Installing systemd services ..."

# CEST daily bot (runs with --schedule, triggers once per day near close)
cp "$BOT_DIR/deploy/trading-bot.service" "$CEST_SERVICE_FILE"
chmod 644 "$CEST_SERVICE_FILE"
info "  → $CEST_SERVICE: CEST daily strategy (cest_main.py --schedule)"

# Intraday bot (scans every N minutes while market is open)
cp "$BOT_DIR/deploy/intraday-bot.service" "$INTRADAY_SERVICE_FILE"
chmod 644 "$INTRADAY_SERVICE_FILE"
info "  → $INTRADAY_SERVICE: intraday scanner (main.py)"

systemctl daemon-reload
systemctl enable "$CEST_SERVICE" "$INTRADAY_SERVICE"

echo ""
info "Both services installed and enabled for startup on boot."
info "Starting services now ..."
systemctl start "$CEST_SERVICE"
systemctl start "$INTRADAY_SERVICE"

sleep 3   # Give them a moment to initialise

echo ""
echo "================================================================"
echo "  DEPLOYMENT COMPLETE — both trading systems active"
echo "================================================================"
echo ""
echo "Service status:"
echo "────────────────────────────────────────"
systemctl status "$CEST_SERVICE" --no-pager || true
echo ""
systemctl status "$INTRADAY_SERVICE" --no-pager || true
echo ""
echo "Useful commands:"
echo "  systemctl status  $CEST_SERVICE       # CEST daily bot status"
echo "  systemctl status  $INTRADAY_SERVICE   # intraday bot status"
echo "  systemctl stop    $CEST_SERVICE       # stop CEST bot"
echo "  systemctl stop    $INTRADAY_SERVICE   # stop intraday bot"
echo "  systemctl restart $CEST_SERVICE       # restart CEST bot"
echo "  systemctl restart $INTRADAY_SERVICE   # restart intraday bot"
echo "  journalctl -u $CEST_SERVICE -f        # CEST live log tail"
echo "  journalctl -u $INTRADAY_SERVICE -f    # intraday live log tail"
echo "  cat $BOT_DIR/logs/heartbeat           # verify intraday bot is alive"
echo "  tail -f $BOT_DIR/logs/app.log         # full application log"
echo "  tail -f $BOT_DIR/logs/trades.log      # order audit trail"
echo "  tail -f $BOT_DIR/logs/cest_bot.log    # CEST strategy log"
echo ""
echo "Log files are in: $BOT_DIR/logs/"
echo "State files in:   $BOT_DIR/data/"
echo "Config file:      $ENV_FILE"
