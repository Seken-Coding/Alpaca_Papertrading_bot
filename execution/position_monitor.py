"""Position monitor — automated management of open bracket positions.

Runs every scheduler tick (60s) when POSITION_MONITOR=true.

Three actions per position (evaluated in order):
1. Trailing stop upgrade — if unrealised gain >= 1.5x entry ATR,
   cancel the static SL and place a trailing stop.
2. Time-based exit — close positions held longer than MAX_HOLD_DAYS.
3. Bracket leg health check — warn if TP/SL orders are orphaned.
"""

import logging
from datetime import datetime, timezone

from alpaca.trading.enums import OrderSide

from broker.client import AlpacaClient
from config.settings import settings
from execution.position_store import PositionStore
from execution.trade_journal import TradeJournal

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")

# Position must be up >= this multiple of entry ATR before trailing stop upgrade
_TRAILING_TRIGGER_MULTIPLIER = 1.5


class PositionMonitor:
    """Monitors open positions and takes automated protective action."""

    def __init__(
        self,
        client: AlpacaClient,
        store: PositionStore,
        journal: TradeJournal,
    ):
        self.client = client
        self.store = store
        self.journal = journal

    def run(self) -> None:
        """Execute one monitoring cycle. All failures are caught internally."""
        if not settings.position_monitor:
            return

        try:
            positions = self.client.get_positions()
        except Exception as exc:
            logger.error("PositionMonitor: could not fetch positions: %s", exc)
            return

        if not positions:
            return

        # Reconcile store against live positions (purge orphaned JSON entries)
        live_symbols = {p.symbol for p in positions}
        self.store.reconcile(live_symbols)

        # Fetch all open orders once (for bracket health check)
        try:
            open_orders = self.client.get_orders()
        except Exception as exc:
            logger.warning(
                "PositionMonitor: could not fetch open orders: %s", exc,
            )
            open_orders = []

        order_symbols = {o.symbol for o in open_orders}

        for position in positions:
            try:
                self._process_position(position, order_symbols)
            except Exception as exc:
                logger.error(
                    "PositionMonitor: error processing %s: %s",
                    position.symbol, exc, exc_info=True,
                )

    def _process_position(self, position, order_symbols: set) -> None:
        symbol = position.symbol
        current_price = float(position.current_price)
        avg_entry = float(position.avg_entry_price)
        qty = int(float(position.qty))

        meta = self.store.get(symbol)

        # ── 1. Trailing stop upgrade ────────────────────────────────
        if (
            meta is not None
            and not meta.get("trailing_upgraded", False)
            and settings.trailing_stop_pct > 0
        ):
            entry_atr = meta.get("entry_atr", 0.0)
            is_long = qty > 0
            gain = (current_price - avg_entry) if is_long else (avg_entry - current_price)

            if entry_atr > 0 and gain >= _TRAILING_TRIGGER_MULTIPLIER * entry_atr:
                logger.info(
                    "PositionMonitor: %s up $%.2f (%.1fx ATR=$%.2f) — upgrading to trailing stop",
                    symbol, gain, gain / entry_atr, entry_atr,
                )
                self._upgrade_to_trailing_stop(symbol, qty, meta)

        # ── 2. Time-based exit ──────────────────────────────────────
        if meta is not None and settings.max_hold_days > 0:
            entry_time_str = meta.get("entry_time", "")
            if entry_time_str:
                try:
                    entry_time = datetime.fromisoformat(entry_time_str)
                    age_days = (datetime.now(timezone.utc) - entry_time).days
                    if age_days >= settings.max_hold_days:
                        logger.info(
                            "PositionMonitor: %s held %d days (max %d) — closing",
                            symbol, age_days, settings.max_hold_days,
                        )
                        self._close_and_journal(
                            symbol, qty, current_price, avg_entry, meta,
                            reason=f"time_exit:{age_days}d",
                        )
                        return  # No further processing after close
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "PositionMonitor: could not parse entry_time for %s: %s",
                        symbol, exc,
                    )

        # ── 3. Bracket leg health check ─────────────────────────────
        if symbol not in order_symbols:
            # No open orders for this symbol — bracket legs may be orphaned
            # Only warn if we have metadata (i.e. we placed this order)
            if meta is not None and not meta.get("trailing_upgraded", False):
                logger.warning(
                    "PositionMonitor: %s has NO open orders — "
                    "bracket legs may be orphaned",
                    symbol,
                )
                trades_logger.warning(
                    "ORPHANED BRACKET | %s | no open orders found", symbol,
                )

    def _upgrade_to_trailing_stop(
        self, symbol: str, qty: int, meta: dict,
    ) -> None:
        """Cancel existing bracket legs and place a trailing stop."""
        try:
            # Cancel all open orders for this symbol (removes static SL/TP legs)
            open_orders = self.client.get_orders()
            cancelled = 0
            for order in open_orders:
                if order.symbol == symbol:
                    try:
                        self.client.cancel_order(str(order.id))
                        cancelled += 1
                    except Exception as exc:
                        logger.warning(
                            "PositionMonitor: could not cancel order %s for %s: %s",
                            order.id, symbol, exc,
                        )

            logger.info(
                "PositionMonitor: cancelled %d open orders for %s",
                cancelled, symbol,
            )

            # Place trailing stop — SELL to close longs, BUY to close shorts
            close_side = OrderSide.SELL if qty > 0 else OrderSide.BUY
            order = self.client.trailing_stop_order(
                symbol=symbol,
                qty=abs(qty),
                side=close_side,
                trail_percent=settings.trailing_stop_pct,
            )
            self.store.mark_trailing_upgraded(symbol)

            trades_logger.info(
                "TRAILING STOP | %s | qty=%d trail=%.1f%% order_id=%s",
                symbol, qty, settings.trailing_stop_pct, order.id,
            )

        except Exception as exc:
            logger.error(
                "PositionMonitor: failed to upgrade %s to trailing stop: %s",
                symbol, exc,
            )

    def _close_and_journal(
        self,
        symbol: str,
        qty: int,
        current_price: float,
        avg_entry: float,
        meta: dict,
        reason: str,
    ) -> None:
        """Close a position and write the EXIT row to the trade journal."""
        try:
            self.client.close_position(symbol)
            trades_logger.info(
                "CLOSED | %s | qty=%d | reason=%s | price~$%.2f",
                symbol, qty, reason, current_price,
            )
        except Exception as exc:
            logger.error(
                "PositionMonitor: failed to close %s: %s", symbol, exc,
            )
            return  # Don't journal a close that didn't happen

        # Compute P/L and hold duration
        pnl = (current_price - avg_entry) * qty
        hold_hours = 0.0
        entry_order_id = meta.get("order_id", "")
        strategy = meta.get("strategy", "unknown")
        entry_time_str = meta.get("entry_time", "")

        if entry_time_str:
            try:
                entry_time = datetime.fromisoformat(entry_time_str)
                hold_hours = (
                    datetime.now(timezone.utc) - entry_time
                ).total_seconds() / 3600
            except (ValueError, TypeError):
                pass

        try:
            self.journal.record_exit(
                symbol=symbol,
                qty=qty,
                price=current_price,
                strategy=strategy,
                reason=reason,
                pnl=pnl,
                hold_duration_hours=hold_hours,
                entry_order_id=entry_order_id,
            )
        except Exception as exc:
            logger.warning(
                "PositionMonitor: journal write failed for %s exit: %s",
                symbol, exc,
            )

        # Remove from store after successful close
        self.store.remove(symbol)
