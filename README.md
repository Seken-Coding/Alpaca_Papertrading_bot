# Alpaca Paper Trading Bot

Automated systematic paper trading bot using the [Alpaca](https://alpaca.markets/) API. Scans US equities for momentum and mean-reversion signals, applies a three-stage risk pipeline, and places bracket orders automatically.

## Features

- **Two strategies** — Momentum (trend-following) and Mean Reversion (oversold/overbought extremes)
- **Three-stage risk pipeline** — portfolio limits, signal quality gate, ATR-based position sizing
- **Bracket orders** — automatic stop-loss and take-profit on every entry
- **Position monitor** — trailing stop upgrades, time-based exits, bracket health checks (every 60s)
- **Market regime filter** — optional SPY SMA-200 bear market gate
- **Dynamic universe discovery** — scan 500+ US stocks via Alpaca's asset API, or use a static 50-symbol watchlist
- **Scan window** — configurable start/end times to skip the chaotic open and rushed close
- **Circuit breakers** — daily loss and drawdown limits halt trading automatically
- **GUI** — Tkinter dashboard with 6 tabs (positions, orders, recommendations, account, log, settings)
- **VPS-ready** — SIGTERM handling, heartbeat file, configurable log directory

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure credentials** — copy `.env.example` to `.env` and fill in your Alpaca API keys:
   ```
   ALPACA_API_KEY=your_api_key
   ALPACA_SECRET_KEY=your_secret_key
   ALPACA_PAPER=true
   ```

3. **Run the bot:**
   ```bash
   # CLI — one-shot scan (default, AUTO_EXECUTE=false)
   python main.py

   # CLI — continuous scheduler (set AUTO_EXECUTE=true in .env)
   python main.py

   # GUI
   python gui_main.py
   ```

## Configuration

All settings are controlled via environment variables in `.env`. See [.env.example](.env.example) for full documentation. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_EXECUTE` | `false` | Place orders automatically or just log signals |
| `SCAN_INTERVAL_MIN` | `5` | Minutes between scans while market is open |
| `MAX_ORDERS_PER_SCAN` | `5` | Max bracket orders per scan cycle |
| `RISK_PER_TRADE_PCT` | `0.02` | Fraction of equity risked per trade (2%) |
| `MAX_POSITION_PCT` | `0.08` | Max fraction of equity in one position (8%) |
| `ATR_STOP_MULTIPLIER` | `1.8` | Stop-loss distance in ATR multiples |
| `MAX_POSITIONS` | `20` | Max concurrent open positions |
| `MAX_DAILY_LOSS_PCT` | `0.04` | Circuit breaker — daily loss limit (4%) |
| `MAX_DRAWDOWN_PCT` | `0.12` | Circuit breaker — drawdown limit (12%) |
| `POSITION_MONITOR` | `true` | Enable trailing stop upgrades and time exits |
| `REGIME_FILTER` | `false` | Block buys when SPY is in bear regime |
| `UNIVERSE` | `static` | `static` (50 symbols) or `dynamic` (500+ via API) |
| `SCAN_START_ET` | `10:00` | Earliest scan time (US/Eastern) |
| `SCAN_END_ET` | `15:30` | Latest scan time (US/Eastern) |

## Project Structure

```
Alpaca_Papertrading_bot/
├── main.py                      # CLI entry point (one-shot or scheduler)
├── gui_main.py                  # GUI entry point
├── logging_config.py            # Logging setup (call first in any entry point)
├── config/
│   └── settings.py              # Env-var based settings
├── strategies/
│   ├── base.py                  # Strategy ABC
│   ├── momentum.py              # Momentum / trend-following strategy
│   ├── mean_reversion.py        # Mean reversion strategy
│   ├── scanner.py               # StrategyScanner — orchestrates screening + evaluation
│   └── screener.py              # StockScreener — universe filtering + dynamic discovery
├── broker/
│   └── client.py                # AlpacaClient — SDK wrapper with retry logic
├── execution/
│   ├── engine.py                # ExecutionEngine — risk gates + bracket order placement
│   ├── position_store.py        # PositionStore — JSON entry metadata (logs/positions.json)
│   ├── trade_journal.py         # TradeJournal — CSV audit trail (logs/trade_journal.csv)
│   ├── position_monitor.py      # PositionMonitor — trailing stops, time exits, health checks
│   └── market_regime.py         # MarketRegimeFilter — SPY SMA-200 regime classifier
├── risk/
│   └── manager.py               # RiskManager — portfolio limits, scoring, position sizing
├── analysis/
│   ├── indicators.py            # 55-column indicator suite (apply_all)
│   ├── scorer.py                # ScoringEngine — regime-adaptive signal scoring
│   ├── signals.py               # SignalGenerator — weighted vote signal generation
│   └── data_loader.py           # Batched bar loading with per-symbol trimming
├── gui/
│   └── app.py                   # TradingApp — Tkinter GUI (6 tabs + log panel)
├── utils/                       # Utility functions
├── tests/                       # Tests
├── deploy/                      # Deployment scripts
├── logs/                        # Runtime logs, positions, trade journal
├── .env.example                 # Documented env-var template
└── requirements.txt             # Python dependencies
```

## How It Works

1. **Screen** — filter the universe by price, volume, and data availability
2. **Compute indicators** — 55-column enrichment via `apply_all()` (once per symbol)
3. **Evaluate strategies** — each strategy scores every symbol (BUY/SELL/HOLD + strength)
4. **Risk gates** — portfolio limits, signal quality threshold, ATR-based position sizing
5. **Execute** — place bracket orders (stop-loss + take-profit) for passing signals
6. **Monitor** — every 60s: upgrade to trailing stop at 1.5x ATR gain, force-close after N days

## License

For educational and paper trading purposes only. Not financial advice.
