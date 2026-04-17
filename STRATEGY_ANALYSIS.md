# Intraday Strategy Analysis

## Active Trading Model
The bot runs a single intraday pipeline in `main.py`:
1. Build a tradable symbol universe.
2. Load OHLCV bars from Alpaca.
3. Compute indicators.
4. Evaluate momentum and mean-reversion strategies.
5. Rank and risk-gate recommendations.
6. Place bracket orders for approved BUY signals.
7. Monitor open positions for trailing-stop upgrades and time exits.

## Strategies in Use
- `MomentumStrategy` (`strategies/momentum.py`)
- `MeanReversionStrategy` (`strategies/mean_reversion.py`)

Both produce normalized recommendations consumed by `ExecutionEngine`.

## Risk and Execution Controls
- Portfolio-level circuit breakers and limits: `risk/manager.py`
- Minimum score threshold and ATR-based position sizing
- Bracket order placement and duplicate-position prevention: `execution/engine.py`
- Post-entry monitoring and lifecycle management: `execution/position_monitor.py`

## Market/Runtime Controls
- Optional SPY regime gate: `execution/market_regime.py`
- Scan interval and execution toggles via `.env`
- Paper-trading mode controlled by `ALPACA_PAPER=true`

## Current Scope
Repository scope is intraday-only, single-account, Alpaca paper trading.
