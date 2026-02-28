"""Position metadata store — persists entry ATR, time, and strategy per symbol.

Written when a bracket order is confirmed in ExecutionEngine.
Read every 60-second monitor tick by PositionMonitor.
Entries are removed when the position is closed.

File: logs/positions.json
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("logs/positions.json")


class PositionStore:
    """JSON-backed store for open position metadata."""

    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record_entry(
        self,
        symbol: str,
        entry_price: float,
        entry_atr: float,
        strategy: str,
        order_id: str,
        shares: int,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> None:
        """Write entry metadata for a newly opened position."""
        data = self._load()
        data[symbol] = {
            "symbol": symbol,
            "entry_price": entry_price,
            "entry_atr": entry_atr,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "strategy": strategy,
            "order_id": order_id,
            "shares": shares,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "trailing_upgraded": False,
        }
        self._save(data)
        logger.debug("PositionStore: recorded entry for %s", symbol)

    def mark_trailing_upgraded(self, symbol: str) -> None:
        """Flag that the trailing stop has been placed for this position."""
        data = self._load()
        if symbol in data:
            data[symbol]["trailing_upgraded"] = True
            self._save(data)

    def remove(self, symbol: str) -> Optional[dict]:
        """Remove and return entry for symbol, or None if not found."""
        data = self._load()
        entry = data.pop(symbol, None)
        if entry is not None:
            self._save(data)
            logger.debug("PositionStore: removed entry for %s", symbol)
        return entry

    def get(self, symbol: str) -> Optional[dict]:
        """Return metadata dict for symbol, or None."""
        return self._load().get(symbol)

    def get_all(self) -> dict:
        """Return a copy of all stored entries."""
        return self._load().copy()

    def reconcile(self, live_symbols: set) -> None:
        """Remove entries for symbols no longer in the live position list."""
        data = self._load()
        stale = set(data.keys()) - live_symbols
        if stale:
            for sym in stale:
                data.pop(sym)
                logger.info("PositionStore: purged stale entry for %s", sym)
            self._save(data)

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "PositionStore: could not read %s: %s — using empty store",
                self._path, exc,
            )
            return {}

    def _save(self, data: dict) -> None:
        try:
            self._path.write_text(
                json.dumps(data, indent=2), encoding="utf-8",
            )
        except OSError as exc:
            logger.error("PositionStore: could not write %s: %s", self._path, exc)
