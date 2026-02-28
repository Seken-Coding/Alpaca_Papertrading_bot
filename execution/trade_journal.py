"""Trade journal — append-only CSV audit trail of every entry and exit.

File: logs/trade_journal.csv
One row per trade event (ENTRY or EXIT).
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_HEADERS = [
    "timestamp", "symbol", "action", "qty", "price",
    "strategy", "reason", "pnl", "hold_duration_hours", "entry_order_id",
]
_DEFAULT_PATH = Path("logs/trade_journal.csv")


class TradeJournal:
    """Append-only CSV writer for trade events."""

    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def record_entry(
        self,
        symbol: str,
        qty: int,
        price: float,
        strategy: str,
        reason: str,
        entry_order_id: str,
    ) -> None:
        """Write an ENTRY row."""
        self._append({
            "timestamp": _now_iso(),
            "symbol": symbol,
            "action": "ENTRY",
            "qty": qty,
            "price": f"{price:.4f}",
            "strategy": strategy,
            "reason": reason,
            "pnl": "",
            "hold_duration_hours": "",
            "entry_order_id": entry_order_id,
        })
        logger.debug("TradeJournal: ENTRY recorded for %s", symbol)

    def record_exit(
        self,
        symbol: str,
        qty: int,
        price: float,
        strategy: str,
        reason: str,
        pnl: float,
        hold_duration_hours: float,
        entry_order_id: str,
    ) -> None:
        """Write an EXIT row."""
        self._append({
            "timestamp": _now_iso(),
            "symbol": symbol,
            "action": "EXIT",
            "qty": qty,
            "price": f"{price:.4f}",
            "strategy": strategy,
            "reason": reason,
            "pnl": f"{pnl:.2f}",
            "hold_duration_hours": f"{hold_duration_hours:.2f}",
            "entry_order_id": entry_order_id,
        })
        logger.debug("TradeJournal: EXIT recorded for %s (pnl=%.2f)", symbol, pnl)

    def _ensure_header(self) -> None:
        if not self._path.exists() or self._path.stat().st_size == 0:
            try:
                with self._path.open("w", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=_HEADERS).writeheader()
            except OSError as exc:
                logger.error(
                    "TradeJournal: could not create %s: %s", self._path, exc,
                )

    def _append(self, row: dict) -> None:
        try:
            with self._path.open("a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=_HEADERS).writerow(row)
        except OSError as exc:
            logger.error(
                "TradeJournal: could not append to %s: %s", self._path, exc,
            )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
