"""CEST State Persistence.

Saves and loads bot state to/from JSON for crash recovery.
State is saved on every cycle to ensure idempotent restarts.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from config import cest_settings as cfg

logger = logging.getLogger(__name__)


@dataclass
class BotState:
    """Persistent bot state."""
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    trading_halted_until: datetime | None = None
    last_universe_scan: str | None = None  # ISO date string
    total_trades: int = 0
    equity_curve_sma50: float = 0.0
    universe: list[str] = field(default_factory=list)

    def update_equity(self, current_equity: float) -> None:
        """Update peak equity and drawdown tracking."""
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        if self.peak_equity > 0:
            self.current_drawdown_pct = (
                (self.peak_equity - current_equity) / self.peak_equity * 100.0
            )
        else:
            self.current_drawdown_pct = 0.0

    def is_halted(self) -> bool:
        """Check if trading is currently halted."""
        if self.trading_halted_until is None:
            return False
        return datetime.now() < self.trading_halted_until

    def halt_trading(self, days: int = None) -> None:
        """Halt trading for a specified number of calendar days."""
        days = days or int(cfg.DD_HALT_DAYS * 1.4)  # Convert trading days to calendar
        self.trading_halted_until = datetime.now() + timedelta(days=days)
        logger.critical(
            "Trading HALTED until %s",
            self.trading_halted_until.isoformat(),
        )


def load_state(path: str = None) -> BotState:
    """Load bot state from JSON file.

    Returns a fresh BotState if file doesn't exist or is corrupt.
    """
    path = path or cfg.STATE_PATH

    if not os.path.exists(path):
        logger.info("No existing state file at %s — starting fresh", path)
        return BotState()

    try:
        with open(path, "r") as f:
            data = json.load(f)

        state = BotState(
            peak_equity=data.get("peak_equity", 0.0),
            current_drawdown_pct=data.get("current_drawdown_pct", 0.0),
            last_universe_scan=data.get("last_universe_scan"),
            total_trades=data.get("total_trades", 0),
            equity_curve_sma50=data.get("equity_curve_sma50", 0.0),
            universe=data.get("universe", []),
        )

        halted = data.get("trading_halted_until")
        if halted:
            try:
                state.trading_halted_until = datetime.fromisoformat(halted)
            except (ValueError, TypeError):
                state.trading_halted_until = None

        logger.info(
            "State loaded: peak_equity=%.2f, drawdown=%.1f%%, trades=%d, universe=%d symbols",
            state.peak_equity, state.current_drawdown_pct,
            state.total_trades, len(state.universe),
        )
        return state

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Corrupt state file %s: %s — starting fresh", path, e)
        return BotState()


def save_state(state: BotState, path: str = None) -> None:
    """Save bot state to JSON file."""
    path = path or cfg.STATE_PATH

    # Ensure directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    data = {
        "peak_equity": state.peak_equity,
        "current_drawdown_pct": state.current_drawdown_pct,
        "trading_halted_until": (
            state.trading_halted_until.isoformat()
            if state.trading_halted_until
            else None
        ),
        "last_universe_scan": state.last_universe_scan,
        "total_trades": state.total_trades,
        "equity_curve_sma50": state.equity_curve_sma50,
        "universe": state.universe,
    }

    try:
        # Write to temp file first, then rename (atomic on most filesystems)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        logger.debug("State saved to %s", path)
    except Exception as e:
        logger.error("Failed to save state: %s", e)


def should_scan_universe(state: BotState) -> bool:
    """Determine if a weekly universe scan is needed.

    Scans on Monday or if last scan is stale (>7 days).
    """
    today = datetime.now().date()

    # Monday check
    is_monday = today.weekday() == 0

    # Staleness check
    if state.last_universe_scan:
        try:
            last_scan = datetime.fromisoformat(state.last_universe_scan).date()
            days_since = (today - last_scan).days
            if days_since >= 7:
                return True
        except (ValueError, TypeError):
            return True

    if is_monday and state.last_universe_scan:
        try:
            last_scan = datetime.fromisoformat(state.last_universe_scan).date()
            if last_scan < today:
                return True
        except (ValueError, TypeError):
            return True

    # First run
    if not state.last_universe_scan:
        return True

    return False
