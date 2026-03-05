"""Abstract broker interface for CEST strategy.

Broker-agnostic base class. Strategy, risk, and analysis modules
must NEVER import from broker/ — they receive data as pandas DataFrames.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BrokerBase(ABC):
    """Abstract base class for all broker implementations."""

    @abstractmethod
    def get_account(self) -> dict:
        """Return account information.

        Returns
        -------
        dict : {'equity': float, 'cash': float, 'buying_power': float}
        """

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """Return list of open positions.

        Returns
        -------
        list[dict] : each with keys:
            'symbol': str, 'qty': int, 'side': str,
            'entry_price': float, 'current_price': float,
            'unrealized_pnl': float
        """

    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Fetch historical OHLCV bars.

        Parameters
        ----------
        symbol    : str - ticker symbol
        timeframe : str - '1Day', '1Hour', etc.
        limit     : int - number of bars

        Returns
        -------
        pd.DataFrame : columns = open, high, low, close, volume.
                        Index = datetime.
        """

    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str,
        limit_price: float = None,
        stop_price: float = None,
    ) -> dict:
        """Submit an order to the broker.

        Parameters
        ----------
        symbol      : str - ticker symbol
        qty         : int - number of shares
        side        : str - 'buy' or 'sell'
        order_type  : str - 'market', 'limit', 'stop', 'stop_limit'
        limit_price : float - for limit/stop_limit orders
        stop_price  : float - for stop/stop_limit orders

        Returns
        -------
        dict : order details including 'id', 'status', etc.
        """

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Returns
        -------
        bool : True if successfully cancelled
        """

    @abstractmethod
    def is_market_open(self) -> bool:
        """Check if market is currently open."""

    @abstractmethod
    def get_clock(self) -> dict:
        """Return market clock information.

        Returns
        -------
        dict : {'is_open': bool, 'next_open': datetime, 'next_close': datetime}
        """
