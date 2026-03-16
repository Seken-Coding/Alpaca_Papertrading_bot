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
#   3. Copies the bot to /opt/trading-bot/ (with per-account directories)
#   4. Creates a Python virtualenv and installs dependencies
#   5. Prompts you to fill in your .env (API keys, automation settings)
#   6. Validates accounts.yaml, verifies env vars, runs pre-flight checks
#   7. Stops old single-bot services (if present) and installs multi-bot service
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

# Create per-account data and log directories from accounts.yaml
ACCOUNTS_YAML="$BOT_DIR/config/accounts.yaml"
if [[ -f "$ACCOUNTS_YAML" ]]; then
    # Extract account IDs — lightweight grep, no Python needed yet
    ACCOUNT_IDS=$(grep -E '^\s+-?\s*id:' "$ACCOUNTS_YAML" | sed 's/.*id:\s*"\?\([^"]*\)"\?.*/\1/')
    for ACCT_ID in $ACCOUNT_IDS; do
        mkdir -p "$BOT_DIR/data/$ACCT_ID"
        mkdir -p "$BOT_DIR/logs/$ACCT_ID"
        info "Created dirs for account '$ACCT_ID'"
    done
else
    warn "accounts.yaml not found — skipping per-account directory setup"
fi

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
# 6. Validate accounts.yaml and .env for multi-bot deployment
# =============================================================================
info "Validating multi-bot configuration ..."

# 6a. Parse accounts.yaml and extract required env var names
if [[ ! -f "$ACCOUNTS_YAML" ]]; then
    err "accounts.yaml not found at $ACCOUNTS_YAML — cannot deploy multi-bot"
fi

# Validate YAML is parseable using the virtualenv Python
sudo -u "$BOT_USER" "$VENV/bin/python" -c "
import yaml, sys
with open('$ACCOUNTS_YAML') as f:
    data = yaml.safe_load(f)
if not data or 'accounts' not in data:
    print('ERROR: accounts.yaml missing \"accounts\" key', file=sys.stderr)
    sys.exit(1)
for acct in data['accounts']:
    for key in ('id', 'bot_type', 'api_key_env', 'secret_key_env'):
        if key not in acct:
            print(f'ERROR: account missing required field \"{key}\"', file=sys.stderr)
            sys.exit(1)
    if acct['bot_type'] not in ('intraday', 'cest'):
        print(f'ERROR: account \"{acct[\"id\"]}\" has invalid bot_type \"{acct[\"bot_type\"]}\"', file=sys.stderr)
        sys.exit(1)
print(f'OK — {len(data[\"accounts\"])} accounts configured')
" || err "accounts.yaml validation failed"

# 6b. Verify required ACCT* env vars exist in .env
REQUIRED_ENVS=$(grep -oE 'ACCT[0-9]+_(API_KEY|SECRET_KEY)' "$ACCOUNTS_YAML" | sort -u)
MISSING_ENVS=""
for VAR in $REQUIRED_ENVS; do
    if ! grep -qE "^${VAR}=" "$ENV_FILE" 2>/dev/null; then
        MISSING_ENVS="${MISSING_ENVS}  ${VAR}\n"
    fi
done

if [[ -n "$MISSING_ENVS" ]]; then
    warn "The following env vars are referenced in accounts.yaml but not set in .env:"
    echo -e "$MISSING_ENVS"
    warn "The multi-bot service will fail to start until these are set."
    read -rp "Continue anyway? [y/N] " CONTINUE
    [[ "$CONTINUE" =~ ^[Yy]$ ]] || err "Aborted — please fill in $ENV_FILE first"
else
    info "All required env vars found in .env"
fi

# 6c. Pre-flight import check — verify all bot modules load without errors
info "Running pre-flight import check ..."
sudo -u "$BOT_USER" "$VENV/bin/python" -c "
import sys
failures = []
modules = [
    'config.settings', 'config.cest_settings', 'config.accounts',
    'broker.client', 'broker.alpaca_broker', 'broker.errors',
    'strategies.momentum', 'strategies.mean_reversion', 'strategies.scanner',
    'strategies.regime', 'strategies.entries', 'strategies.exits',
    'strategies.pyramiding', 'strategies.spy_macro', 'strategies.darvas_box',
    'execution.engine', 'execution.position_store', 'execution.trade_journal',
    'execution.position_monitor', 'execution.market_regime',
    'analysis.indicators', 'analysis.scorer', 'analysis.signals',
    'risk.manager', 'risk.cest_risk_manager', 'risk.position_sizing',
    'risk.gap_protection',
    'utils.state', 'utils.trade_tracker',
    'multi.context', 'multi.runner', 'multi.dashboard',
    'logging_config',
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

info "Multi-bot configuration validated successfully"

# =============================================================================
# 7. Stop legacy services (if present) and install multi-bot service
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

# Show deployed account summary
echo "Deployed accounts:"
echo "────────────────────────────────────────"
if [[ -f "$ACCOUNTS_YAML" ]]; then
    sudo -u "$BOT_USER" "$VENV/bin/python" -c "
import yaml
with open('$ACCOUNTS_YAML') as f:
    data = yaml.safe_load(f)
for acct in data['accounts']:
    print(f'  {acct[\"id\"]:<25s} ({acct[\"bot_type\"]:<8s})  {acct[\"label\"]}')
"
fi
echo ""
echo "Useful commands:"
echo "  systemctl status  $MULTI_SERVICE       # check multi-bot status"
echo "  systemctl stop    $MULTI_SERVICE       # stop all accounts"
echo "  systemctl restart $MULTI_SERVICE       # restart all accounts"
echo "  journalctl -u $MULTI_SERVICE -f        # live log tail"
echo ""
echo "  cd $BOT_DIR && $VENV/bin/python multi_main.py --dashboard  # performance leaderboard"
echo "  cd $BOT_DIR && $VENV/bin/python multi_main.py --promote    # strategy promotion report"
echo ""
echo "Per-account logs:"
if [[ -f "$ACCOUNTS_YAML" ]]; then
    for ACCT_ID in $(grep -E '^\s+-?\s*id:' "$ACCOUNTS_YAML" | sed 's/.*id:\s*"\?\([^"]*\)"\?.*/\1/'); do
        echo "  tail -f $BOT_DIR/logs/$ACCT_ID/app.log"
    done
fi
echo ""
echo "Log files are in: $BOT_DIR/logs/<account_id>/"
echo "State files in:   $BOT_DIR/data/<account_id>/"
echo "Account config:   $ACCOUNTS_YAML"
echo "Env config:       $ENV_FILE"
