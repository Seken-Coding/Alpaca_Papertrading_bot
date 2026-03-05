"""Alpaca broker implementation for CEST strategy.

Implements BrokerBase using the alpaca-py SDK.
Connects to paper trading or live trading based on configuration.
"""

import logging
import os
import time
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

from broker.base import BrokerBase

logger = logging.getLogger(__name__)

load_dotenv()

# Lazy-imported at module level so tests can patch them
try:
    from alpaca.trading.client import TradingClient
    from alpaca.data.historical import StockHistoricalDataClient
except ImportError:
    TradingClient = None
    StockHistoricalDataClient = None


class AlpacaBroker(BrokerBase):
    """Alpaca Markets broker implementation."""

    def __init__(self):
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"

        if not api_key or not secret_key:
            raise EnvironmentError(
                "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY environment variables"
            )

        if TradingClient is None:
            raise ImportError(
                "alpaca-py is required. Install with: pip install alpaca-py"
            )

        self._trading_client = TradingClient(
            api_key, secret_key, paper=paper,
        )
        self._data_client = StockHistoricalDataClient(api_key, secret_key)
        self._paper = paper
        logger.info(
            "Alpaca broker initialized (paper=%s)", paper,
        )

    def get_account(self) -> dict:
        """Return account equity, cash, and buying power."""
        try:
            account = self._trading_client.get_account()
            return {
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
            }
        except Exception as e:
            logger.error("Failed to get account: %s", e)
            raise

    def get_positions(self) -> list[dict]:
        """Return list of open positions."""
        try:
            positions = self._trading_client.get_all_positions()
            result = []
            for pos in positions:
                result.append({
                    "symbol": pos.symbol,
                    "qty": int(pos.qty),
                    "side": "LONG" if float(pos.qty) > 0 else "SHORT",
                    "entry_price": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price),
                    "unrealized_pnl": float(pos.unrealized_pl),
                })
            return result
        except Exception as e:
            logger.error("Failed to get positions: %s", e)
            return []

    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Fetch historical bars from Alpaca data API."""
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame

            tf_map = {
                "1Day": TimeFrame.Day,
                "1Hour": TimeFrame.Hour,
                "1Min": TimeFrame.Minute,
            }
            tf = tf_map.get(timeframe, TimeFrame.Day)

            # Calculate start date based on limit (add buffer for weekends/holidays)
            buffer_days = int(limit * 1.5) + 30
            start = datetime.now() - timedelta(days=buffer_days)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                limit=limit,
            )

            bars = self._data_client.get_stock_bars(request)

            if symbol not in bars or len(bars[symbol]) == 0:
                logger.warning("No bar data returned for %s", symbol)
                return pd.DataFrame()

            data = []
            for bar in bars[symbol]:
                data.append({
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": int(bar.volume),
                    "timestamp": bar.timestamp,
                })

            df = pd.DataFrame(data)
            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)

            # Trim to requested limit
            if len(df) > limit:
                df = df.iloc[-limit:]

            return df

        except Exception as e:
            logger.error("Failed to get bars for %s: %s", symbol, e)
            return pd.DataFrame()

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str,
        limit_price: float = None,
        stop_price: float = None,
    ) -> dict:
        """Submit an order via Alpaca."""
        try:
            from alpaca.trading.requests import (
                LimitOrderRequest,
                MarketOrderRequest,
                StopLimitOrderRequest,
                StopOrderRequest,
            )
            from alpaca.trading.enums import OrderSide, TimeInForce

            alpaca_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            if order_type == "market":
                request = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                )
            elif order_type == "limit":
                request = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                )
            elif order_type == "stop":
                request = StopOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    stop_price=stop_price,
                )
            elif order_type == "stop_limit":
                request = StopLimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                    stop_price=stop_price,
                )
            else:
                raise ValueError(f"Unknown order type: {order_type}")

            order = self._trading_client.submit_order(request)

            result = {
                "id": str(order.id),
                "symbol": order.symbol,
                "qty": int(order.qty),
                "side": str(order.side),
                "type": str(order.type),
                "status": str(order.status),
            }

            logger.info(
                "Order submitted: %s %s %d %s @ %s | ID=%s | Status=%s",
                side, symbol, qty, order_type,
                limit_price or stop_price or "market",
                result["id"], result["status"],
            )

            return result

        except Exception as e:
            logger.error("Failed to submit order %s %s %d: %s", side, symbol, qty, e)
            raise

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            self._trading_client.cancel_order_by_id(order_id)
            logger.info("Order cancelled: %s", order_id)
            return True
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)
            return False

    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        try:
            clock = self._trading_client.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error("Failed to get market status: %s", e)
            return False

    def get_clock(self) -> dict:
        """Return market clock information."""
        try:
            clock = self._trading_client.get_clock()
            return {
                "is_open": clock.is_open,
                "next_open": clock.next_open,
                "next_close": clock.next_close,
            }
        except Exception as e:
            logger.error("Failed to get clock: %s", e)
            return {
                "is_open": False,
                "next_open": None,
                "next_close": None,
            }

    def get_asset(self, symbol: str) -> dict | None:
        """Get asset information (for checking shortability, etc.)."""
        try:
            asset = self._trading_client.get_asset(symbol)
            return {
                "symbol": asset.symbol,
                "name": asset.name,
                "exchange": str(asset.exchange),
                "tradable": asset.tradable,
                "shortable": asset.shortable,
                "easy_to_borrow": asset.easy_to_borrow,
            }
        except Exception as e:
            logger.warning("Failed to get asset info for %s: %s", symbol, e)
            return None

    def get_all_assets(self, exchange: str = None) -> list[dict]:
        """Get all tradable assets, optionally filtered by exchange."""
        try:
            from alpaca.trading.requests import GetAssetsRequest
            from alpaca.trading.enums import AssetStatus

            request = GetAssetsRequest(status=AssetStatus.ACTIVE)
            assets = self._trading_client.get_all_assets(request)

            result = []
            for asset in assets:
                if not asset.tradable:
                    continue
                if exchange and str(asset.exchange) != exchange:
                    continue
                result.append({
                    "symbol": asset.symbol,
                    "name": asset.name,
                    "exchange": str(asset.exchange),
                    "shortable": asset.shortable,
                })
            return result
        except Exception as e:
            logger.error("Failed to get assets: %s", e)
            return []
