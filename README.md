# Alpaca Paper Trading Bot

Automated intraday paper-trading bot using the [Alpaca](https://alpaca.markets/) API.

## What It Does

- Scans US equities for momentum and mean-reversion setups
- Applies a three-stage risk pipeline (portfolio gate, score gate, sizing gate)
- Places bracket orders (entry + stop-loss + take-profit)
- Monitors open positions for trailing-stop upgrades and max-hold exits
- Supports static or dynamic universe selection

## Entry Points

- `main.py` — intraday scanner + execution loop
- `gui_main.py` — optional Tkinter GUI

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure credentials:
   ```bash
   cp .env.example .env
   ```
   Set:
   ```
   ALPACA_API_KEY=...
   ALPACA_SECRET_KEY=...
   ALPACA_PAPER=true
   ```

3. Run the bot:
   ```bash
   python main.py
   ```

## Core Runtime Flow

1. Load settings from `.env`
2. Connect to Alpaca
3. Screen symbols (`strategies/screener.py`)
4. Load bars + compute indicators (`analysis/data_loader.py`, `analysis/indicators.py`)
5. Evaluate momentum + mean-reversion strategies
6. Risk-gate and execute through `execution/engine.py`
7. Monitor positions every scheduler tick via `execution/position_monitor.py`

## Configuration

All runtime settings are in `.env`:

- `AUTO_EXECUTE`
- `SCAN_INTERVAL_MIN`
- `MAX_ORDERS_PER_SCAN`
- `MAX_POSITION_PCT`
- `RISK_PER_TRADE_PCT`
- `ATR_STOP_MULTIPLIER`
- `MIN_RISK_REWARD`
- `MAX_POSITIONS`
- `MIN_BUYING_POWER`
- `MAX_DAILY_LOSS_PCT`
- `MAX_DRAWDOWN_PCT`
- `MIN_SCORE_THRESHOLD`
- `POSITION_MONITOR`
- `TRAILING_STOP_PCT`
- `MAX_HOLD_DAYS`
- `REGIME_FILTER`
- `SCAN_START_ET`
- `SCAN_END_ET`
- `UNIVERSE`
- `UNIVERSE_CACHE_TTL`

## Deployment (systemd)

- Service unit: `deploy/intraday-bot.service`
- Setup script: `deploy/setup.sh`

The setup script installs and enables only `intraday-bot`.

## License

For educational and paper-trading purposes only. Not financial advice.
