# Audit Findings — Alpaca Paper Trading Bot

**Date:** 2026-03-06
**Auditor:** Automated comprehensive audit

---

## Architecture Overview

```
                          ┌─────────────┐
                          │  Entry      │
                          │  Points     │
                          └──────┬──────┘
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ main.py  │ │cest_main │ │gui_main  │
              │ (CLI)    │ │ (CEST)   │ │ (Tkinter)│
              └────┬─────┘ └────┬─────┘ └────┬─────┘
                   │            │            │
        ┌──────────┴──────┐    │    ┌───────┘
        ▼                 ▼    ▼    ▼
  ┌──────────┐    ┌────────────────────┐
  │ broker/  │    │  strategies/       │
  │ client   │    │  momentum, mr,     │
  │ alpaca_  │    │  scanner, screener │
  │ broker   │    │  regime, entries,  │
  └────┬─────┘    │  exits, patterns   │
       │          └─────────┬──────────┘
       │                    │
       ▼                    ▼
  ┌──────────┐    ┌────────────────────┐
  │ Alpaca   │    │  analysis/         │
  │ API      │    │  indicators,       │
  │ (Paper)  │    │  cest_indicators,  │
  │          │    │  scorer, signals,  │
  └──────────┘    │  data_loader       │
                  └────────────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │execution/│ │  risk/   │ │  utils/  │
        │engine,   │ │manager,  │ │state,    │
        │monitor,  │ │cest_risk,│ │tracker   │
        │store,    │ │pos_size  │ └──────────┘
        │journal   │ └──────────┘
        └──────────┘
```

**Two trading systems coexist:**
1. **Main bot** (`main.py`): Intraday scanner with momentum/mean-reversion strategies, bracket orders
2. **CEST bot** (`cest_main.py`): Daily "Composite Edge Systematic Trader" with regime detection, confluence scoring

Both share the `alpaca-py` SDK and some analysis modules.

---

## Issues Found

### 🔴 CRITICAL (2) — ALL FIXED

1. ~~**`cest_main.py:59` — Missing `import logging.handlers` at module level**~~
   **FIXED**: Moved `import logging.handlers` to module-level imports; removed redundant import inside `main()`.

2. ~~**`config/settings.py:67` — Module-level Settings() instantiation crashes on import**~~
   **FIXED**: Replaced with `_SettingsProxy` lazy singleton — `Settings()` is only constructed on first attribute access.

### 🟠 HIGH (5) — 4 FIXED, 1 NOTED

1. ~~**`requirements.txt` — Dependencies not pinned to exact versions**~~
   **FIXED**: All deps pinned to exact versions. Removed unused `pytz` and `requests`.

2. ~~**`cest_main.py:403` — `schedule` package used but optional dependency not handled gracefully**~~
   **FIXED**: Package pinned in requirements.txt.

3. **Two separate broker client implementations exist** — NOT FIXED (by design)
   `broker/client.py` (AlpacaClient) and `broker/alpaca_broker.py` (AlpacaBroker) serve different systems. Consolidation would require significant refactoring with risk of regression. Noted as tech debt.

4. ~~**`broker/alpaca_broker.py:79` — `get_positions()` silently returns empty list on error**~~
   **FIXED**: Now re-raises the exception after logging, letting callers handle failures explicitly.

5. ~~**`config/settings.py` defaults mismatch `.env.example`**~~
   **FIXED**: `MAX_ORDERS_PER_SCAN` default aligned to 5. `MAX_POSITION_PCT` mismatch documented — code defaults (0.05) are intentionally more conservative than `.env.example` suggestions (0.08).

### 🟡 MEDIUM (8) — 5 FIXED, 3 NOTED

1. ~~**`.gitignore` excludes `*.env` — overly broad**~~
   **FIXED**: Changed to `.env.*` with `!.env.example` exception.

2. ~~**No `data/` directory in `.gitignore`**~~
   **FIXED**: Added `data/` to `.gitignore`.

3. **`gui/app.py` — GUI code is very large (900+ lines) in a single file** — NOT FIXED
   Functional as-is. Noted as tech debt.

4. **`broker/ib_broker.py` — Stub implementation always raises NotImplementedError** — NOT FIXED
   Left as placeholder for future IB integration.

5. **Missing `__init__.py` exports consistency** — NOT FIXED
   Low priority; current behavior doesn't cause bugs.

6. ~~**`execution/position_monitor.py` — Only handles LONG positions for trailing stop**~~
   **FIXED**: Gain calculation now direction-aware; trailing stop side determined by position sign.

7. ~~**`risk/manager.py` — RiskConfig reads env vars at class instantiation time**~~
   **FIXED**: Fields use static defaults; env var overrides applied in `__post_init__`.

8. ~~**`strategies/screener.py:51-58` — `_ALLOWED_EXCHANGES` may reference enum values that don't exist in all alpaca-py versions**~~
   **FIXED**: Uses `getattr()` with fallback for missing enum values.

### 🔵 LOW (6)

1. **No `py.typed` marker or `mypy` configuration**
2. **`deploy/setup.sh` references Python 3.13 specifically — not flexible**
3. **README project structure section is outdated (missing CEST-related files)**
4. **No CHANGELOG.md exists**
5. **`.env.example` doesn't document CEST-specific settings (BROKER, etc.)**
6. **Test coverage is focused on CEST modules; no tests for `analysis/indicators.py` or `analysis/scorer.py`**

---

## Dependency Inventory

| Package | Required Version | Current Spec | Status |
|---------|-----------------|-------------|--------|
| alpaca-py | ≥0.21.0 | `>=0.21.0` | ⚠️ Not pinned |
| python-dotenv | ≥1.0.0 | `>=1.0.0` | ⚠️ Not pinned |
| pandas | ≥2.0.0 | `>=2.0.0` | ⚠️ Not pinned |
| numpy | ≥1.24.0 | `>=1.24.0` | ⚠️ Not pinned |
| pytz | ≥2023.3 | `>=2023.3` | ⚠️ Not pinned (also not actually imported anywhere — uses `zoneinfo`) |
| schedule | ≥1.2.0 | `>=1.2.0` | ⚠️ Not pinned |
| pytest | ≥7.0.0 | `>=7.0.0` | ⚠️ Not pinned (dev dependency) |
| requests | ≥2.28.0 | `>=2.28.0` | ⚠️ Not pinned (not directly imported — pulled in by alpaca-py) |

**Notes:**
- `pytz` is listed but never imported; the codebase uses `zoneinfo` (stdlib in Python 3.9+)
- `requests` is not directly imported; it's a transitive dependency of `alpaca-py`
- `tkinter` is needed for GUI but is a stdlib module
- `ib_insync` is commented out (IB broker is a stub)

---

## Phase 1 Summary

The codebase is well-structured with good separation of concerns. Two parallel trading systems (main intraday + CEST daily) share broker and analysis infrastructure. The primary issues are:
- One critical bug (missing import in cest_main.py)
- Settings module crashes without env vars (blocks testing)
- Dependencies not pinned
- Minor inconsistencies between documented defaults and code defaults
- Good test coverage for CEST modules; gaps in main bot module tests
