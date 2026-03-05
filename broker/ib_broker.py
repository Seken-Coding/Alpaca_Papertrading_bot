"""Interactive Brokers broker stub for CEST strategy.

Implements BrokerBase interface using ib_insync.
Currently a stub — all methods raise NotImplementedError.

To activate:
  1. pip install ib_insync
  2. Set BROKER = "ib" in config/cest_settings.py
  3. Implement the TODO methods below
"""

import logging

import pandas as pd

from broker.base import BrokerBase

logger = logging.getLogger(__name__)


class IBBroker(BrokerBase):
    """Interactive Brokers implementation (stub)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = None

        # TODO: IB implementation
        # from ib_insync import IB
        # self._ib = IB()
        # self._ib.connect(host, port, clientId=client_id)
        logger.warning("IB broker is a stub — not connected")

    def get_account(self) -> dict:
        # TODO: IB implementation
        raise NotImplementedError("IB broker not yet implemented")

    def get_positions(self) -> list[dict]:
        # TODO: IB implementation
        raise NotImplementedError("IB broker not yet implemented")

    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        # TODO: IB implementation
        raise NotImplementedError("IB broker not yet implemented")

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str,
        limit_price: float = None,
        stop_price: float = None,
    ) -> dict:
        # TODO: IB implementation
        raise NotImplementedError("IB broker not yet implemented")

    def cancel_order(self, order_id: str) -> bool:
        # TODO: IB implementation
        raise NotImplementedError("IB broker not yet implemented")

    def is_market_open(self) -> bool:
        # TODO: IB implementation
        raise NotImplementedError("IB broker not yet implemented")

    def get_clock(self) -> dict:
        # TODO: IB implementation
        raise NotImplementedError("IB broker not yet implemented")
