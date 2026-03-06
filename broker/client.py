"""Alpaca broker client — wraps the alpaca-py SDK for trading and market data."""

import logging
import time as _time
from typing import List, Optional

from broker.errors import clean_broker_error

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetAssetsRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    TrailingStopOrderRequest,
    ReplaceOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import (
    AssetClass,
    AssetStatus,
    OrderClass,
    OrderSide,
    OrderStatus,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

logger = logging.getLogger(__name__)

# Transient error types that warrant a retry (network blips, rate-limits)
_RETRYABLE = (ConnectionError, TimeoutError, OSError)


def _retry_api(fn, max_attempts: int = 3, backoff: float = 1.5):
    """Call *fn()* with exponential backoff on transient failures.

    Retries up to *max_attempts* times for transient errors (network blips,
    timeouts).  Non-transient exceptions (e.g. Alpaca API errors for bad
    credentials or invalid data) are re-raised immediately so the caller can
    handle them.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                raise
            wait = backoff ** attempt   # 1.0 s, 1.5 s on successive failures
            logger.warning(
                "API call failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, max_attempts, exc, wait,
            )
            _time.sleep(wait)
        except Exception:
            raise  # Non-transient error — fail immediately
    raise last_exc  # unreachable, but satisfies type checkers


class AlpacaClient:
    """Unified wrapper around Alpaca's Trading and Market Data clients."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self._trading = TradingClient(api_key, secret_key, paper=paper)
        self._data = StockHistoricalDataClient(api_key, secret_key)
        self._paper = paper
        logger.info("AlpacaClient initialized (paper=%s)", paper)

    # ── Account ──────────────────────────────────────────────────────────

    def get_account(self):
        """Return the current account information (retries on transient errors)."""
        return _retry_api(self._trading.get_account)

    # ── Orders ───────────────────────────────────────────────────────────

    def market_order(
        self,
        symbol: str,
        qty: float,
        side: OrderSide,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ):
        """Submit a market order."""
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=time_in_force,
        )
        order = self._trading.submit_order(order_data=req)
        logger.info("Market order submitted: %s %s %s", side.value, qty, symbol)
        return order

    def limit_order(
        self,
        symbol: str,
        qty: float,
        side: OrderSide,
        limit_price: float,
        time_in_force: TimeInForce = TimeInForce.GTC,
    ):
        """Submit a limit order."""
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=limit_price,
            time_in_force=time_in_force,
        )
        order = self._trading.submit_order(order_data=req)
        logger.info(
            "Limit order submitted: %s %s %s @ %s",
            side.value, qty, symbol, limit_price,
        )
        return order

    def get_orders(
        self,
        status: QueryOrderStatus = QueryOrderStatus.OPEN,
        side: Optional[OrderSide] = None,
    ) -> list:
        """Retrieve orders, optionally filtered by status and side."""
        params = GetOrdersRequest(status=status, side=side)
        return self._trading.get_orders(filter=params)

    def cancel_all_orders(self) -> list:
        """Cancel all open orders."""
        statuses = self._trading.cancel_orders()
        logger.info("Cancelled all open orders")
        return statuses

    def stop_order(
        self,
        symbol: str,
        qty: float,
        side: OrderSide,
        stop_price: float,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ):
        """Submit a stop order."""
        req = StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            stop_price=stop_price,
            time_in_force=time_in_force,
        )
        order = self._trading.submit_order(order_data=req)
        logger.info(
            "Stop order submitted: %s %s %s trigger@%s",
            side.value, qty, symbol, stop_price,
        )
        return order

    def stop_limit_order(
        self,
        symbol: str,
        qty: float,
        side: OrderSide,
        stop_price: float,
        limit_price: float,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ):
        """Submit a stop-limit order."""
        req = StopLimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            stop_price=stop_price,
            limit_price=limit_price,
            time_in_force=time_in_force,
        )
        order = self._trading.submit_order(order_data=req)
        logger.info(
            "Stop-limit order submitted: %s %s %s stop@%s limit@%s",
            side.value, qty, symbol, stop_price, limit_price,
        )
        return order

    def trailing_stop_order(
        self,
        symbol: str,
        qty: float,
        side: OrderSide,
        trail_percent: Optional[float] = None,
        trail_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
    ):
        """Submit a trailing stop order.

        Provide either trail_percent (e.g. 1.0 for 1%) or trail_price
        (absolute dollar offset from high-water mark).
        """
        if trail_percent is None and trail_price is None:
            raise ValueError("Must provide either trail_percent or trail_price")
        req = TrailingStopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            trail_percent=trail_percent,
            trail_price=trail_price,
            time_in_force=time_in_force,
        )
        order = self._trading.submit_order(order_data=req)
        trail_val = f"{trail_percent}%" if trail_percent else f"${trail_price}"
        logger.info(
            "Trailing stop order submitted: %s %s %s trail=%s",
            side.value, qty, symbol, trail_val,
        )
        return order

    def bracket_order(
        self,
        symbol: str,
        qty: float,
        side: OrderSide,
        take_profit_price: float,
        stop_loss_price: float,
        stop_loss_limit_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
    ):
        """Submit a bracket (OTO/OCO) order.

        A bracket order consists of an entry market order with a
        take-profit limit and stop-loss attached.  Uses GTC so the
        TP/SL legs persist across trading sessions until triggered.
        """
        stop_loss_params = {"stop_price": stop_loss_price}
        if stop_loss_limit_price is not None:
            stop_loss_params["limit_price"] = stop_loss_limit_price

        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=time_in_force,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=take_profit_price),
            stop_loss=StopLossRequest(**stop_loss_params),
        )
        order = self._trading.submit_order(order_data=req)
        logger.info(
            "Bracket order submitted: %s %s %s TP@%s SL@%s",
            side.value, qty, symbol, take_profit_price, stop_loss_price,
        )
        return order

    def notional_market_order(
        self,
        symbol: str,
        notional: float,
        side: OrderSide,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ):
        """Submit a market order by dollar amount (fractional shares)."""
        req = MarketOrderRequest(
            symbol=symbol,
            notional=notional,
            side=side,
            time_in_force=time_in_force,
        )
        order = self._trading.submit_order(order_data=req)
        logger.info(
            "Notional market order submitted: %s $%s of %s",
            side.value, notional, symbol,
        )
        return order

    def get_order_by_id(self, order_id: str):
        """Retrieve a single order by its ID."""
        return self._trading.get_order_by_id(order_id)

    def replace_order(
        self,
        order_id: str,
        qty: Optional[float] = None,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        trail: Optional[float] = None,
        time_in_force: Optional[TimeInForce] = None,
    ):
        """Modify an existing open order."""
        req = ReplaceOrderRequest(
            qty=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            trail=trail,
            time_in_force=time_in_force,
        )
        order = self._trading.replace_order_by_id(order_id, req)
        logger.info("Replaced order %s", order_id)
        return order

    def cancel_order(self, order_id: str):
        """Cancel a specific order by ID."""
        self._trading.cancel_order_by_id(order_id)
        logger.info("Cancelled order %s", order_id)

    # ── Positions

    def get_positions(self) -> list:
        """Return all open positions (retries on transient errors)."""
        return _retry_api(self._trading.get_all_positions)

    def close_all_positions(self, cancel_orders: bool = True) -> list:
        """Close all positions and optionally cancel open orders."""
        responses = self._trading.close_all_positions(cancel_orders=cancel_orders)
        logger.info("Closed all positions (cancel_orders=%s)", cancel_orders)
        return responses

    def close_position(self, symbol: str):
        """Close a position for a specific symbol (retries on transient errors)."""
        _retry_api(lambda: self._trading.close_position(symbol))
        logger.info("Closed position for %s", symbol)

    # ── Assets ───────────────────────────────────────────────────────────

    def get_assets(self, asset_class: AssetClass = AssetClass.US_EQUITY) -> list:
        """Return active tradable assets for the given asset class."""
        req = GetAssetsRequest(
            asset_class=asset_class,
            status=AssetStatus.ACTIVE,
        )
        return _retry_api(lambda: self._trading.get_all_assets(req))

    # ── Market clock ─────────────────────────────────────────────────────

    def get_clock(self):
        """Return the Alpaca market clock (is_open, next_open, next_close).
        Retries on transient errors."""
        return _retry_api(self._trading.get_clock)

    def is_market_open(self) -> bool:
        """Return True if the US equity market is currently open.

        Uses retry logic for transient errors.  Only returns False after
        retries are exhausted, and logs the failure so it's visible in logs.
        """
        try:
            clock = _retry_api(self._trading.get_clock)
            return bool(clock.is_open)
        except Exception as exc:
            logger.error(
                "Failed to check market status: %s — assuming market closed",
                clean_broker_error(exc),
            )
            return False

    def wait_for_bracket_attachment(
        self, order_id: str, timeout: float = 10.0
    ) -> bool:
        """Poll until the bracket order is accepted or definitively rejected.

        Returns True when the order is accepted/new/pending (safe to count as
        placed).  Returns False if Alpaca rejects or cancels it.  If *timeout*
        elapses without a terminal status, returns True optimistically (the
        order will still exist in Alpaca's system).

        Do NOT retry order submission based on this result — the order exists
        regardless of what this returns.
        """
        _ACCEPTED = {"new", "accepted", "pending_new", "partially_filled", "filled"}
        _REJECTED = {"rejected", "canceled", "expired"}

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            try:
                order = self.get_order_by_id(order_id)
                status = str(order.status.value).lower()
                if status in _ACCEPTED:
                    logger.debug(
                        "Bracket order %s confirmed (status=%s)", order_id, status
                    )
                    return True
                if status in _REJECTED:
                    logger.warning(
                        "Bracket order %s %s by broker", order_id, status
                    )
                    return False
                # pending_cancel, replaced, etc. — keep polling
            except Exception as exc:
                logger.warning(
                    "Could not poll order %s status: %s", order_id,
                    clean_broker_error(exc),
                )
            _time.sleep(1.0)

        logger.warning(
            "Bracket order %s: timed out after %.0fs waiting for confirmation "
            "(assuming accepted)",
            order_id, timeout,
        )
        return True  # Optimistic — treat as placed if no rejection seen

    # ── Market Data ──────────────────────────────────────────────────────

    def get_bars(
        self,
        symbols: List[str],
        timeframe: TimeFrame,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = None,
    ):
        """Fetch historical bar data for one or more symbols."""
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
        )
        return _retry_api(lambda: self._data.get_stock_bars(req))
