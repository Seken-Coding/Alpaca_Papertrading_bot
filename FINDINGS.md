# Repository Findings

## Scope
Current repository is intentionally intraday-only and single-account (Alpaca paper).

## Runtime Architecture
- Entry point: `main.py`
- Optional UI: `gui_main.py`
- Config loading: `config/settings.py`
- Alpaca wrapper: `broker/client.py`
- Strategy scan: `strategies/scanner.py` + momentum/mean-reversion strategies
- Signal and indicators: `analysis/`
- Risk pipeline: `risk/manager.py`
- Execution: `execution/engine.py`
- Position state and journaling: `execution/position_store.py`, `execution/trade_journal.py`
- Ongoing position management: `execution/position_monitor.py`
- Deployment: `deploy/setup.sh`, `deploy/intraday-bot.service`

## Removed Legacy Areas
- Legacy daily trader stack
- Multi-account orchestration and account registry/config files
- Legacy systemd units replaced by intraday-only service

## Verification Snapshot (2026-04-17)
- `python -m compileall -q .` passed
- `pytest -q` passed: 110 tests
