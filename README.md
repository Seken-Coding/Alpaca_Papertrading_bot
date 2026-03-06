# Alpaca Paper Trading Bot

Automated systematic paper trading bot using the [Alpaca](https://alpaca.markets/) API. Contains two independent trading systems that share broker and analysis infrastructure.

## Trading Systems

### 1. Intraday Scanner (`main.py`)
Scans US equities for momentum and mean-reversion signals on intraday/daily data, applies a three-stage risk pipeline, and places bracket orders automatically.

### 2. CEST Daily Bot (`cest_main.py`)
**Composite Edge Systematic Trader** — runs once daily on daily bars. Features regime detection (5 market states), confluence-scored entries, VCP pattern detection, graduated drawdown circuit breakers, and equity curve filtering.

## Features

- **Momentum + Mean Reversion strategies** (intraday bot)
- **Trend + MR entries with confluence scoring** (CEST bot)
- **5 market regimes** — TREND_UP, TREND_DOWN, RANGE, HIGH_VOL, CRISIS
- **Three-stage risk pipeline** — portfolio limits, signal quality gate, ATR-based position sizing
- **Bracket orders** — automatic stop-loss and take-profit on every entry
- **Position monitor** — trailing stop upgrades, time-based exits, bracket health checks
- **Market regime filter** — optional SPY SMA-200 bear market gate (intraday bot)
- **Drawdown circuit breakers** — graduated response (75% → 50% → 25% → halt)
- **Equity curve filter** — 50-trade SMA reduces position sizes during drawdowns
- **VCP pattern detection** — Volatility Contraction Pattern (Minervini)
- **Dynamic universe discovery** — scan 500+ US stocks via Alpaca API, or use static watchlists
- **GUI** — Tkinter dashboard with 6 tabs (positions, orders, recommendations, account, log, settings)
- **VPS-ready** — SIGTERM handling, systemd service file, configurable log directory

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

3. **Run:**
   ```bash
   # Intraday bot — one-shot scan (default, AUTO_EXECUTE=false)
   python main.py

   # Intraday bot — continuous scheduler (set AUTO_EXECUTE=true in .env)
   python main.py

   # CEST daily bot — single cycle
   python cest_main.py

   # CEST daily bot — scheduled (runs at 15:55 ET daily)
   python cest_main.py --schedule

   # GUI
   python gui_main.py
   ```

## Configuration

All settings are controlled via environment variables in `.env`. See [.env.example](.env.example) for full documentation.

### Intraday Bot Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_EXECUTE` | `false` | Place orders automatically or just log signals |
| `SCAN_INTERVAL_MIN` | `5` | Minutes between scans while market is open |
| `MAX_ORDERS_PER_SCAN` | `5` | Max bracket orders per scan cycle |
| `RISK_PER_TRADE_PCT` | `0.02` | Fraction of equity risked per trade |
| `MAX_POSITION_PCT` | `0.08` | Max fraction of equity in one position |
| `ATR_STOP_MULTIPLIER` | `1.8` | Stop-loss distance in ATR multiples |
| `MAX_POSITIONS` | `20` | Max concurrent open positions |
| `MAX_DAILY_LOSS_PCT` | `0.04` | Circuit breaker — daily loss limit |
| `MAX_DRAWDOWN_PCT` | `0.12` | Circuit breaker — drawdown limit |
| `POSITION_MONITOR` | `true` | Enable trailing stop upgrades and time exits |
| `REGIME_FILTER` | `false` | Block buys when SPY is in bear regime |
| `UNIVERSE` | `static` | `static` (50 symbols) or `dynamic` (500+ via API) |

### CEST Bot Settings

CEST parameters are in `config/cest_settings.py`. Key settings include risk per trade (1%), max positions (10), 5 regime thresholds, entry/exit multipliers, and drawdown levels.

## Project Structure

```
Alpaca_Papertrading_bot/
├── main.py                      # Intraday bot entry point
├── cest_main.py                 # CEST daily bot entry point
├── gui_main.py                  # GUI entry point
├── logging_config.py            # Logging setup (rotating file + console)
├── config/
│   ├── settings.py              # Intraday bot settings (env vars)
│   ├── cest_settings.py         # CEST bot parameters (all magic numbers)
│   └── universe.py              # Universe scanning and ranking
├── strategies/
│   ├── base.py                  # Strategy ABC
│   ├── momentum.py              # Momentum / trend-following strategy
│   ├── mean_reversion.py        # Mean reversion strategy
│   ├── scanner.py               # StrategyScanner — screening + evaluation
│   ├── screener.py              # StockScreener — universe filtering
│   ├── regime.py                # CEST regime detection (5 states)
│   ├── entries.py               # CEST entry signal generation
│   ├── exits.py                 # CEST exit management
│   └── patterns.py              # VCP pattern detection
├── broker/
│   ├── base.py                  # BrokerBase ABC
│   ├── client.py                # AlpacaClient (intraday bot)
│   ├── alpaca_broker.py         # AlpacaBroker (CEST bot)
│   └── ib_broker.py             # IB broker stub (not implemented)
├── execution/
│   ├── engine.py                # ExecutionEngine — risk gates + bracket orders
│   ├── position_store.py        # JSON position metadata
│   ├── trade_journal.py         # CSV audit trail
│   ├── position_monitor.py      # Trailing stops, time exits, health checks
│   └── market_regime.py         # SPY SMA-200 regime classifier
├── risk/
│   ├── manager.py               # RiskManager (intraday bot)
│   ├── cest_risk_manager.py     # CEST risk management
│   └── position_sizing.py       # CEST position sizing
├── analysis/
│   ├── indicators.py            # 55-column indicator suite
│   ├── cest_indicators.py       # CEST indicator functions
│   ├── scorer.py                # Regime-adaptive signal scoring
│   ├── signals.py               # Weighted vote signal generation
│   └── data_loader.py           # Batched bar loading
├── utils/
│   ├── state.py                 # BotState — JSON crash recovery
│   └── trade_tracker.py         # Trade lifecycle tracking
├── gui/
│   └── app.py                   # Tkinter GUI (6 tabs)
├── tests/                       # Test suite (93 tests)
├── deploy/
│   ├── setup.sh                 # VPS deployment script
│   └── trading-bot.service      # systemd unit file
├── data/                        # Runtime state (gitignored)
├── logs/                        # Runtime logs (gitignored)
├── .env.example                 # Documented env-var template
├── requirements.txt             # Pinned Python dependencies
├── FINDINGS.md                  # Audit findings
└── CHANGELOG.md                 # Version history
```

## How It Works

### Intraday Bot Flow
1. **Screen** — filter the universe by price, volume, and data availability
2. **Compute indicators** — 55-column enrichment via `apply_all()`
3. **Evaluate strategies** — momentum + mean reversion score every symbol
4. **Risk gates** — portfolio limits, signal quality threshold, ATR-based sizing
5. **Execute** — place bracket orders (stop-loss + take-profit)
6. **Monitor** — every 60s: trailing stop upgrades, time-based exits

### CEST Bot Flow
1. **Load state** — restore from crash-safe JSON
2. **Universe scan** — weekly ranking by 6-month relative strength
3. **Fetch bars** — daily OHLCV for all symbols
4. **Detect regime** — classify each symbol's market state
5. **Generate signals** — confluence-scored entry signals
6. **Risk filters** — portfolio constraints, correlation, drawdown
7. **Execute entries** — position-sized market orders
8. **Manage exits** — stop-loss, trailing, time, partial profit, breakeven

## License

For educational and paper trading purposes only. Not financial advice.
