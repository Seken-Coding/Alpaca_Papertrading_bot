# Changelog

## [1.2.0] - 2026-04-17

### Changed
- Removed the legacy daily trader and all related modules, configs, services, and tests.
- Removed multi-account orchestration and legacy account registry/config artifacts.
- Standardized runtime and deployment on a single intraday entry point: `main.py`.
- Simplified deployment to a single systemd unit: `deploy/intraday-bot.service`.
- Updated `.env.example` and `README.md` for single-account Alpaca paper trading.
- Updated tests to validate intraday-only layout and startup/import behavior.

### Verified
- Full repository compile check passes (`python -m compileall -q .`).
- Full test suite passes (`pytest`): 110 passed.
