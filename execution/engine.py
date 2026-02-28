"""Automatic execution engine.

Converts scanner recommendations into live bracket orders, gated by the
full three-stage risk pipeline:

  1. Portfolio gate  — positions / buying power / daily loss / drawdown
  2. Signal gate     — minimum strength threshold
  3. Trade gate      — ATR-based position sizing + minimum R:R

Only BUY signals generate orders in the current implementation (short
selling paper positions requires margin; add SELL logic when ready).

Usage
-----
    engine = ExecutionEngine(client, risk_manager, max_orders=3)
    summary = engine.execute(recommendations)
    print(summary)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from alpaca.trading.enums import OrderSide

from broker.client import AlpacaClient
from risk.manager import RiskManager
from strategies.scanner import Recommendation
from analysis.signals import Signal
from execution.position_store import PositionStore
from execution.trade_journal import TradeJournal

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")
risk_logger = logging.getLogger("risk")


# ─────────────────────────────────────────────────────────────────────────────
# Result object
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExecutionSummary:
    """Outcome of a single execute() call."""
    placed:  List[str] = field(default_factory=list)   # symbols with orders placed
    blocked: List[str] = field(default_factory=list)   # blocked by risk gates
    skipped: List[str] = field(default_factory=list)   # already have position / SELL
    errors:  List[str] = field(default_factory=list)   # API / unexpected failures

    def __str__(self) -> str:
        return (
            f"ExecutionSummary — placed={len(self.placed)} "
            f"blocked={len(self.blocked)} skipped={len(self.skipped)} "
            f"errors={len(self.errors)} | "
            f"placed: {self.placed or 'none'}"
        )

    @property
    def any_placed(self) -> bool:
        return bool(self.placed)


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class ExecutionEngine:
    """Translates scanner recommendations into bracket orders.

    Parameters
    ----------
    client:
        Initialised AlpacaClient.
    risk_manager:
        Initialised RiskManager with session equity already set.
    max_orders:
        Hard cap on orders placed per scan run (circuit breaker).
    require_market_open:
        If True (default) abort execution when the market is closed.
        Set False only for testing / paper-trading during off-hours.
    """

    def __init__(
        self,
        client: AlpacaClient,
        risk_manager: RiskManager,
        max_orders: int = 3,
        require_market_open: bool = True,
        position_store: Optional[PositionStore] = None,
        trade_journal: Optional[TradeJournal] = None,
    ):
        self.client = client
        self.risk = risk_manager
        self.max_orders = max_orders
        self.require_market_open = require_market_open
        self._store = position_store
        self._journal = trade_journal

    # ── Public API ───────────────────────────────────────────────────────

    def execute(self, recommendations: List[Recommendation]) -> ExecutionSummary:
        """Process *recommendations* and place bracket orders where appropriate.

        Recommendations are already sorted by strength (highest first) coming
        out of StrategyScanner.scan().  The engine respects that ordering and
        stops after placing *max_orders* orders.
        """
        summary = ExecutionSummary()

        # ── Market hours gate ────────────────────────────────────────────
        if self.require_market_open and not self.client.is_market_open():
            logger.warning("ExecutionEngine: market is closed — skipping execution")
            risk_logger.warning("Execution aborted: market closed")
            summary.skipped = [r.symbol for r in recommendations]
            return summary

        # ── Fetch live account state ──────────────────────────────────────
        try:
            account = self.client.get_account()
            equity = float(account.equity)
            buying_power = float(account.buying_power)
            open_positions = self.client.get_positions()
        except Exception as exc:
            logger.error("ExecutionEngine: could not fetch account state: %s", exc)
            summary.errors.append(f"account fetch: {exc}")
            return summary

        self.risk.update_equity(equity)

        # Build set of symbols that already have an open position
        open_symbols = {p.symbol for p in open_positions}

        # ── Portfolio gate ────────────────────────────────────────────────
        port_gate = self.risk.check_portfolio_limits(
            position_count=len(open_positions),
            equity=equity,
            buying_power=buying_power,
        )
        if not port_gate.allowed:
            risk_logger.warning("Portfolio gate BLOCKED all execution: %s", port_gate.reason)
            logger.warning("Execution blocked by risk manager: %s", port_gate.reason)
            summary.blocked = [r.symbol for r in recommendations]
            return summary

        # ── Per-recommendation loop ───────────────────────────────────────
        placed_count = 0

        for rec in recommendations:
            if placed_count >= self.max_orders:
                logger.info("Max orders per scan (%d) reached — stopping", self.max_orders)
                break

            # Only BUY supported (short selling needs margin / separate logic)
            if rec.signal != Signal.BUY:
                logger.warning(
                    "SELL signal for %s (strength=%.0f%%) skipped — "
                    "short selling not implemented (requires margin account)",
                    rec.symbol, rec.strength * 100,
                )
                summary.skipped.append(rec.symbol)
                continue

            # Skip if position already open
            if rec.symbol in open_symbols:
                logger.debug("Skipping %s — position already open", rec.symbol)
                summary.skipped.append(rec.symbol)
                continue

            # ── Signal quality gate (strength 0-1 → 0-100 scale) ─────────
            score_gate = self.risk.validate_score(rec.strength * 100)
            if not score_gate.allowed:
                risk_logger.info(
                    "Score gate BLOCKED %s (strength=%.0f%%): %s",
                    rec.symbol, rec.strength * 100, score_gate.reason,
                )
                summary.blocked.append(rec.symbol)
                continue

            # ── Position sizing gate ──────────────────────────────────────
            sizing = self.risk.calculate_position_size(
                symbol=rec.symbol,
                price=rec.price,
                atr=rec.atr,
                equity=equity,
                direction="BUY",
            )
            if not sizing.passes_risk:
                risk_logger.info(
                    "Sizing gate BLOCKED %s: %s", rec.symbol, sizing.rejection_reason
                )
                summary.blocked.append(rec.symbol)
                continue

            # ── Place bracket order ───────────────────────────────────────
            try:
                order = self.client.bracket_order(
                    symbol=rec.symbol,
                    qty=float(sizing.shares),
                    side=OrderSide.BUY,
                    take_profit_price=round(sizing.take_profit_price, 2),
                    stop_loss_price=round(sizing.stop_loss_price, 2),
                )

                # Verify the bracket was accepted — not immediately rejected
                accepted = self.client.wait_for_bracket_attachment(str(order.id))
                if not accepted:
                    trades_logger.error(
                        "ORDER REJECTED | %s | broker rejected bracket order",
                        rec.symbol,
                    )
                    summary.errors.append(
                        f"{rec.symbol}: bracket order rejected by broker"
                    )
                    continue

                placed_count += 1
                open_symbols.add(rec.symbol)   # Prevent duplicate in same run

                # ── Record in position store ──────────────────────────
                if self._store is not None:
                    try:
                        self._store.record_entry(
                            symbol=rec.symbol,
                            entry_price=rec.price,
                            entry_atr=rec.atr,
                            strategy=rec.strategy,
                            order_id=str(order.id),
                            shares=sizing.shares,
                            stop_loss_price=sizing.stop_loss_price,
                            take_profit_price=sizing.take_profit_price,
                        )
                    except Exception as exc:
                        logger.warning(
                            "PositionStore write failed for %s: %s",
                            rec.symbol, exc,
                        )

                # ── Record in trade journal ───────────────────────────
                if self._journal is not None:
                    try:
                        self._journal.record_entry(
                            symbol=rec.symbol,
                            qty=sizing.shares,
                            price=rec.price,
                            strategy=rec.strategy,
                            reason=rec.reason,
                            entry_order_id=str(order.id),
                        )
                    except Exception as exc:
                        logger.warning(
                            "TradeJournal write failed for %s: %s",
                            rec.symbol, exc,
                        )

                trades_logger.info(
                    "EXECUTED | %s | BUY %d shares @ $%.2f | SL $%.2f | TP $%.2f | "
                    "R:R %.2f | strategy=%s | strength=%.0f%%",
                    rec.symbol, sizing.shares, rec.price,
                    sizing.stop_loss_price, sizing.take_profit_price,
                    sizing.risk_reward, rec.strategy, rec.strength * 100,
                )
                logger.info(
                    "Order placed: BUY %d %s | SL $%.2f TP $%.2f",
                    sizing.shares, rec.symbol,
                    sizing.stop_loss_price, sizing.take_profit_price,
                )
                summary.placed.append(rec.symbol)

            except Exception as exc:
                logger.error("Failed to place order for %s: %s", rec.symbol, exc)
                trades_logger.error("ORDER FAILED | %s | %s", rec.symbol, exc)
                summary.errors.append(f"{rec.symbol}: {exc}")

        risk_logger.info("Execution complete — %s", summary)
        return summary
