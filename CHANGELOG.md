# Changelog

## [1.1.0] - 2026-03-06

### Fixed
- **CRITICAL**: `cest_main.py` — moved `import logging.handlers` to module level; previously nested inside `main()`, causing `AttributeError` if `setup_logging()` was called before `main()`
- **CRITICAL**: `config/settings.py` — deferred `Settings()` instantiation via lazy proxy; previously crashed on import when env vars were not set, blocking test suites
- **HIGH**: `broker/alpaca_broker.py` — `get_positions()` now raises on API error instead of silently returning `[]`, which could cause the CEST bot to place duplicate entries during network failures
- **HIGH**: `execution/position_monitor.py` — trailing stop upgrade now correctly handles SHORT positions (was hardcoded to `OrderSide.SELL`)
- **HIGH**: `config/settings.py` — `MAX_ORDERS_PER_SCAN` default changed from 3 to 5 to match `.env.example`
- **MEDIUM**: `risk/manager.py` — `RiskConfig` env var overrides now read at construction time via `__post_init__` instead of at class-definition time, fixing test-mocking issues
- **MEDIUM**: `strategies/screener.py` — `_ALLOWED_EXCHANGES` now uses `getattr()` for graceful handling of enum values missing in older `alpaca-py` versions

### Changed
- **Dependencies**: pinned all versions (`alpaca-py==0.43.2`, `pandas==3.0.1`, `numpy==2.4.2`, etc.)
- **Dependencies**: removed unused `pytz` (codebase uses `zoneinfo`) and `requests` (transitive dep of `alpaca-py`)
- **`.gitignore`**: changed `*.env` to `.env.*` with `!.env.example` exception; added `data/` directory
- **`.env.example`**: added CEST bot settings documentation (BROKER, DAILY_RUN_TIME)
- **`README.md`**: rewritten to cover both trading systems, updated project structure

## [1.0.0] - Initial Release

- Intraday scanner with momentum and mean-reversion strategies
- CEST daily bot with regime detection and confluence scoring
- Bracket order execution with position monitoring
- Tkinter GUI dashboard
- VPS deployment support via systemd
