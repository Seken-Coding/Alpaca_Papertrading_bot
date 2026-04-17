#!/usr/bin/env bash
# =============================================================================
# Alpaca Paper Trading Bot — VPS Setup Script (Intraday Only)
# Tested on: Ubuntu 22.04 LTS / 24.04 LTS
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
#   5. Prompts you to fill in your .env (single Alpaca paper account)
#   6. Validates .env and runs pre-flight import checks
#   7. Installs/starts intraday-bot systemd service
# =============================================================================

set -euo pipefail

BOT_DIR="/opt/trading-bot"
BOT_USER="trading"
PYTHON_BIN="python3.13"
TARGET_SERVICE="intraday-bot"
TARGET_SERVICE_SRC="deploy/intraday-bot.service"

# Legacy services to clean up if present
LEGACY_SERVICES=("multi-bot" "trading-bot")

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Must run as root ─────────────────────────────────────────────────────────
[[ "$EUID" -eq 0 ]] || err "Please run as root: sudo ./setup.sh"

# ── Detect source directory ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_SOURCE="$(dirname "$SCRIPT_DIR")"

if [[ ! -f "$BOT_SOURCE/main.py" ]]; then
    err "Could not find main.py in $BOT_SOURCE. Run this script from deploy/."
fi

if [[ ! -f "$BOT_SOURCE/$TARGET_SERVICE_SRC" ]]; then
    err "Missing service file: $TARGET_SERVICE_SRC"
fi

info "Bot source directory: $BOT_SOURCE"
info "Mode: intraday only"

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

rsync -a --exclude='.git' \
          --exclude='*.pyc' \
          --exclude='__pycache__' \
          --exclude='venv' \
          --exclude='.venv' \
          --exclude='logs' \
          --exclude='data' \
          --exclude='.env' \
          "$BOT_SOURCE/" "$BOT_DIR/"

mkdir -p "$BOT_DIR/logs"
mkdir -p "$BOT_DIR/data"

chown -R "$BOT_USER:$BOT_USER" "$BOT_DIR"
info "Files deployed to $BOT_DIR"

# Ensure runtime paths and log files stay writable by the service user.
# This prevents boot/update failures when files were previously created by root.
install -d -o "$BOT_USER" -g "$BOT_USER" -m 775 "$BOT_DIR/logs" "$BOT_DIR/data"
touch \
    "$BOT_DIR/logs/app.log" \
    "$BOT_DIR/logs/errors.log" \
    "$BOT_DIR/logs/trades.log" \
    "$BOT_DIR/logs/risk.log" \
    "$BOT_DIR/logs/scanner.log" \
    "$BOT_DIR/logs/bot_status.log" \
    "$BOT_DIR/logs/trade_journal.csv"
chown "$BOT_USER:$BOT_USER" "$BOT_DIR"/logs/*
chmod 664 "$BOT_DIR"/logs/*

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
    echo "  Required keys for paper trading:"
    echo "    ALPACA_API_KEY=<your Alpaca paper API key>"
    echo "    ALPACA_SECRET_KEY=<your Alpaca paper secret key>"
    echo "    ALPACA_PAPER=true"
    echo "================================================================"
    echo ""
    read -rp "Press Enter after you have filled in $ENV_FILE ..."
fi

# Keep env readable by the service user across updates.
chown "$BOT_USER:$BOT_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# =============================================================================
# 6. Validate .env and run pre-flight checks
# =============================================================================
info "Validating intraday configuration ..."

if ! grep -qE '^\s*ALPACA_API_KEY\s*=\s*[^[:space:]#]+' "$ENV_FILE"; then
    err "ALPACA_API_KEY is missing or empty in $ENV_FILE"
fi

if ! grep -qE '^\s*ALPACA_SECRET_KEY\s*=\s*[^[:space:]#]+' "$ENV_FILE"; then
    err "ALPACA_SECRET_KEY is missing or empty in $ENV_FILE"
fi

if grep -qE '^\s*ALPACA_PAPER\s*=\s*false\s*$' "$ENV_FILE"; then
    warn "ALPACA_PAPER=false detected in $ENV_FILE"
    warn "This repository is intended for paper trading only."
    read -rp "Continue anyway? [y/N] " CONTINUE
    [[ "$CONTINUE" =~ ^[Yy]$ ]] || err "Aborted — set ALPACA_PAPER=true and rerun"
fi

info "Running pre-flight import check ..."
sudo -u "$BOT_USER" "$VENV/bin/python" -c "
import os, sys
os.chdir('$BOT_DIR')
sys.path.insert(0, '$BOT_DIR')
failures = []
modules = [
    'config.settings',
    'broker.client', 'broker.errors',
    'strategies.momentum', 'strategies.mean_reversion',
    'strategies.scanner', 'strategies.screener',
    'execution.engine', 'execution.position_store',
    'execution.trade_journal', 'execution.position_monitor',
    'execution.market_regime',
    'analysis.indicators', 'analysis.scorer',
    'analysis.signals', 'analysis.data_loader',
    'risk.manager', 'utils.bar_cache', 'logging_config',
]
for mod_name in modules:
    try:
        __import__(mod_name)
    except Exception as e:
        failures.append(f'{mod_name}: {e}')
if failures:
    print('IMPORT FAILURES:', file=sys.stderr)
    for f in failures:
        print(f'  {f}', file=sys.stderr)
    sys.exit(1)
print(f'OK — {len(modules)} modules imported successfully')
" || err "Pre-flight check failed — fix import errors before deploying"

info "Intraday configuration validated successfully"

# =============================================================================
# 7. Install intraday service
# =============================================================================
TARGET_SERVICE_FILE="/etc/systemd/system/${TARGET_SERVICE}.service"

# Stop and remove legacy service units if present.
for SVC in "${LEGACY_SERVICES[@]}"; do
    SVC_FILE="/etc/systemd/system/${SVC}.service"

    if systemctl is-active --quiet "$SVC" 2>/dev/null; then
        info "Stopping service '$SVC' ..."
        systemctl stop "$SVC"
    fi

    if systemctl is-enabled --quiet "$SVC" 2>/dev/null; then
        info "Disabling service '$SVC' ..."
        systemctl disable "$SVC"
    fi

    if [[ -f "$SVC_FILE" ]]; then
        info "Removing service file: $SVC_FILE"
        rm -f "$SVC_FILE"
    fi
done

# Stop current intraday service before replacing unit file
if systemctl is-active --quiet "$TARGET_SERVICE" 2>/dev/null; then
    info "Stopping service '$TARGET_SERVICE' ..."
    systemctl stop "$TARGET_SERVICE"
fi

info "Installing $TARGET_SERVICE service ..."
cp "$BOT_DIR/$TARGET_SERVICE_SRC" "$TARGET_SERVICE_FILE"
chmod 644 "$TARGET_SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$TARGET_SERVICE"

echo ""
info "$TARGET_SERVICE service installed and enabled for startup on boot."
info "Starting $TARGET_SERVICE service now ..."
systemctl start "$TARGET_SERVICE"

sleep 5

echo ""
echo "================================================================"
echo "  DEPLOYMENT COMPLETE — intraday trading bot active"
echo "================================================================"
echo ""
echo "Service status:"
echo "────────────────────────────────────────"
systemctl status "$TARGET_SERVICE" --no-pager || true
echo ""
echo "Useful commands:"
echo "  systemctl status  $TARGET_SERVICE"
echo "  systemctl stop    $TARGET_SERVICE"
echo "  systemctl restart $TARGET_SERVICE"
echo "  journalctl -u $TARGET_SERVICE -f"
echo ""
echo "Runtime files:"
echo "  Logs:  $BOT_DIR/logs/"
echo "  Data:  $BOT_DIR/data/"
echo "  Env:   $ENV_FILE"
