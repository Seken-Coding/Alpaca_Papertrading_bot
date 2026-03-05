"""CEST Trade Tracker — records and manages trade lifecycle.

Tracks every trade with full metadata. Persists to CSV (append-only).
Loads on startup to populate equity curve filter.
"""

import csv
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from config import cest_settings as cfg

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Complete record of a single trade."""
    symbol: str
    direction: str                    # 'LONG' or 'SHORT'
    entry_price: float
    entry_date: datetime
    stop_loss: float
    initial_risk: float               # |entry - stop| per share
    position_size: int                # shares
    regime_at_entry: str
    strategy_type: str                # 'TREND' or 'MEAN_REVERSION'
    confluence_score: int
    exit_price: float = None
    exit_date: datetime = None
    exit_reason: str = None           # 'STOP_LOSS', 'TRAILING_STOP', 'TARGET',
                                      # 'TIME_EXIT', 'RSI_EXIT', 'BREAKEVEN', 'MANUAL'
    r_multiple: float = None          # (exit - entry) / initial_risk
    pnl_dollars: float = None
    bars_held: int = None
    partial_taken: bool = False
    breakeven_triggered: bool = False
    highest_close_since_entry: float = None
    lowest_close_since_entry: float = None

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    def update_bar(self, close_price: float) -> None:
        """Update tracking fields with the latest bar's close."""
        if self.bars_held is None:
            self.bars_held = 0
        self.bars_held += 1

        if self.highest_close_since_entry is None or close_price > self.highest_close_since_entry:
            self.highest_close_since_entry = close_price

        if self.lowest_close_since_entry is None or close_price < self.lowest_close_since_entry:
            self.lowest_close_since_entry = close_price

    def close_trade(self, exit_price: float, exit_reason: str, exit_date: datetime = None) -> None:
        """Mark trade as closed and calculate final metrics."""
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        self.exit_date = exit_date or datetime.now()

        if self.initial_risk > 0:
            if self.direction == "LONG":
                self.r_multiple = (exit_price - self.entry_price) / self.initial_risk
                self.pnl_dollars = (exit_price - self.entry_price) * self.position_size
            else:
                self.r_multiple = (self.entry_price - exit_price) / self.initial_risk
                self.pnl_dollars = (self.entry_price - exit_price) * self.position_size
        else:
            self.r_multiple = 0.0
            self.pnl_dollars = 0.0

        logger.info(
            "Trade closed: %s %s | Entry=%.2f Exit=%.2f | R=%.2f | P&L=$%.2f | "
            "Bars=%d | Reason=%s",
            self.direction, self.symbol, self.entry_price, exit_price,
            self.r_multiple, self.pnl_dollars,
            self.bars_held or 0, exit_reason,
        )


# CSV column order
_CSV_COLUMNS = [
    "symbol", "direction", "entry_price", "entry_date", "stop_loss",
    "initial_risk", "position_size", "regime_at_entry", "strategy_type",
    "confluence_score", "exit_price", "exit_date", "exit_reason",
    "r_multiple", "pnl_dollars", "bars_held", "partial_taken",
    "breakeven_triggered", "highest_close_since_entry", "lowest_close_since_entry",
]


class TradeTracker:
    """Manages trade records with CSV persistence."""

    def __init__(self, log_path: str = None):
        self._log_path = log_path or cfg.TRADE_LOG_PATH
        self._trades: list[TradeRecord] = []
        self._open_trades: dict[str, TradeRecord] = {}  # symbol -> trade

        # Ensure directory exists
        Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)

        # Load existing trades
        self._load_from_csv()

    def _load_from_csv(self) -> None:
        """Load trade history from CSV file."""
        if not os.path.exists(self._log_path):
            return

        try:
            with open(self._log_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trade = self._row_to_trade(row)
                    self._trades.append(trade)
                    if trade.is_open:
                        self._open_trades[trade.symbol] = trade

            logger.info(
                "Loaded %d trades from %s (%d open)",
                len(self._trades), self._log_path, len(self._open_trades),
            )
        except Exception as e:
            logger.error("Failed to load trade log: %s", e)

    def _row_to_trade(self, row: dict) -> TradeRecord:
        """Convert a CSV row to a TradeRecord."""
        def _float_or_none(val):
            if val is None or val == "" or val == "None":
                return None
            return float(val)

        def _int_or_none(val):
            if val is None or val == "" or val == "None":
                return None
            return int(val)

        def _dt_or_none(val):
            if val is None or val == "" or val == "None":
                return None
            try:
                return datetime.fromisoformat(val)
            except (ValueError, TypeError):
                return None

        def _bool_val(val):
            return str(val).lower() in ("true", "1", "yes")

        return TradeRecord(
            symbol=row.get("symbol", ""),
            direction=row.get("direction", "LONG"),
            entry_price=float(row.get("entry_price", 0)),
            entry_date=_dt_or_none(row.get("entry_date")) or datetime.now(),
            stop_loss=float(row.get("stop_loss", 0)),
            initial_risk=float(row.get("initial_risk", 0)),
            position_size=int(row.get("position_size", 0)),
            regime_at_entry=row.get("regime_at_entry", "RANGE"),
            strategy_type=row.get("strategy_type", "TREND"),
            confluence_score=int(row.get("confluence_score", 0)),
            exit_price=_float_or_none(row.get("exit_price")),
            exit_date=_dt_or_none(row.get("exit_date")),
            exit_reason=row.get("exit_reason") or None,
            r_multiple=_float_or_none(row.get("r_multiple")),
            pnl_dollars=_float_or_none(row.get("pnl_dollars")),
            bars_held=_int_or_none(row.get("bars_held")),
            partial_taken=_bool_val(row.get("partial_taken", "false")),
            breakeven_triggered=_bool_val(row.get("breakeven_triggered", "false")),
            highest_close_since_entry=_float_or_none(row.get("highest_close_since_entry")),
            lowest_close_since_entry=_float_or_none(row.get("lowest_close_since_entry")),
        )

    def _append_to_csv(self, trade: TradeRecord) -> None:
        """Append a single trade record to the CSV file."""
        file_exists = os.path.exists(self._log_path) and os.path.getsize(self._log_path) > 0

        try:
            with open(self._log_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
                if not file_exists:
                    writer.writeheader()

                row = {}
                for col in _CSV_COLUMNS:
                    val = getattr(trade, col, None)
                    if isinstance(val, datetime):
                        val = val.isoformat()
                    row[col] = val

                writer.writerow(row)
        except Exception as e:
            logger.error("Failed to write trade log: %s", e)

    def _update_csv(self) -> None:
        """Rewrite the entire CSV (used when updating existing records)."""
        try:
            with open(self._log_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
                writer.writeheader()
                for trade in self._trades:
                    row = {}
                    for col in _CSV_COLUMNS:
                        val = getattr(trade, col, None)
                        if isinstance(val, datetime):
                            val = val.isoformat()
                        row[col] = val
                    writer.writerow(row)
        except Exception as e:
            logger.error("Failed to update trade log: %s", e)

    def record_entry(self, trade: TradeRecord) -> None:
        """Record a new trade entry."""
        self._trades.append(trade)
        self._open_trades[trade.symbol] = trade
        self._append_to_csv(trade)

        logger.info(
            "ENTRY recorded: %s %s | Price=%.2f | Stop=%.2f | Risk=%.2f | "
            "Shares=%d | Regime=%s | Strategy=%s | Confluence=%d",
            trade.direction, trade.symbol, trade.entry_price, trade.stop_loss,
            trade.initial_risk, trade.position_size, trade.regime_at_entry,
            trade.strategy_type, trade.confluence_score,
        )

    def record_exit(self, symbol: str, exit_price: float, exit_reason: str) -> TradeRecord | None:
        """Record a trade exit."""
        trade = self._open_trades.pop(symbol, None)
        if trade is None:
            logger.warning("No open trade found for %s", symbol)
            return None

        trade.close_trade(exit_price, exit_reason)
        self._update_csv()
        return trade

    def get_open_trade(self, symbol: str) -> TradeRecord | None:
        """Get the open trade for a symbol."""
        return self._open_trades.get(symbol)

    def get_all_open_trades(self) -> dict[str, TradeRecord]:
        """Get all open trades."""
        return dict(self._open_trades)

    def get_trade_results(self) -> list[float]:
        """Get list of P&L for all closed trades (for equity curve filter)."""
        return [
            t.pnl_dollars
            for t in self._trades
            if not t.is_open and t.pnl_dollars is not None
        ]

    def get_closed_trades(self) -> list[TradeRecord]:
        """Get all closed trades."""
        return [t for t in self._trades if not t.is_open]

    @property
    def total_trades(self) -> int:
        return len(self._trades)

    @property
    def open_count(self) -> int:
        return len(self._open_trades)
