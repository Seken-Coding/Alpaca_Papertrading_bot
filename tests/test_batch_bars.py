"""Tests for batched bar fetching and universe scanning."""

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _make_bars_df(n=252, base_price=100.0):
    """Create a realistic OHLCV DataFrame with n rows."""
    dates = pd.date_range(end=datetime.now(), periods=n, freq="B")
    rng = np.random.default_rng(42)
    close = base_price + np.cumsum(rng.normal(0, 1, n))
    close = np.maximum(close, 1.0)  # keep positive
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(500_000, 5_000_000, n),
        },
        index=dates,
    )


class TestAlpacaBrokerGetBarsBatch:
    """Test AlpacaBroker.get_bars_batch with mocked SDK."""

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_batch_returns_multiple_symbols(self):
        """Batch call returns data for all symbols in one API request."""
        mock_data_req = MagicMock()
        mock_tf = MagicMock()
        with patch.dict(sys.modules, {
            "alpaca.data.requests": mock_data_req,
            "alpaca.data.timeframe": mock_tf,
        }), patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC:
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            # Mock bar objects
            def make_mock_bar(o, h, l, c, v, ts):
                bar = MagicMock()
                bar.open = o
                bar.high = h
                bar.low = l
                bar.close = c
                bar.volume = v
                bar.timestamp = ts
                return bar

            ts = datetime(2024, 1, 2)
            mock_bars = {
                "AAPL": [make_mock_bar(150, 155, 148, 153, 1000000, ts)],
                "MSFT": [make_mock_bar(380, 385, 375, 382, 2000000, ts)],
            }
            # Make the mock support `in` and `[]` (dict-like)
            MockDC.return_value.get_stock_bars.return_value = mock_bars

            result = broker.get_bars_batch(["AAPL", "MSFT"], "1Day", 252)

            assert "AAPL" in result
            assert "MSFT" in result
            assert result["AAPL"]["close"].iloc[0] == 153.0
            assert result["MSFT"]["close"].iloc[0] == 382.0

            # Verify only ONE API call was made
            MockDC.return_value.get_stock_bars.assert_called_once()

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_batch_empty_symbols(self):
        """Empty symbol list returns empty dict without API call."""
        with patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC:
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            result = broker.get_bars_batch([], "1Day", 252)
            assert result == {}
            MockDC.return_value.get_stock_bars.assert_not_called()

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_batch_handles_missing_symbols(self):
        """Symbols with no data are omitted from results."""
        mock_data_req = MagicMock()
        mock_tf = MagicMock()
        with patch.dict(sys.modules, {
            "alpaca.data.requests": mock_data_req,
            "alpaca.data.timeframe": mock_tf,
        }), patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC:
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            ts = datetime(2024, 1, 2)
            bar = MagicMock()
            bar.open = 150
            bar.high = 155
            bar.low = 148
            bar.close = 153
            bar.volume = 1000000
            bar.timestamp = ts

            # Only AAPL has data; MSFT is missing from response
            mock_bars = {"AAPL": [bar]}
            MockDC.return_value.get_stock_bars.return_value = mock_bars

            result = broker.get_bars_batch(["AAPL", "MSFT"], "1Day", 252)
            assert "AAPL" in result
            assert "MSFT" not in result

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_batch_api_error_returns_empty(self):
        """API errors return empty dict instead of raising."""
        with patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC:
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            MockDC.return_value.get_stock_bars.side_effect = Exception("rate limited")
            result = broker.get_bars_batch(["AAPL"], "1Day", 252)
            assert result == {}


class TestBrokerBaseGetBarsBatchFallback:
    """Test BrokerBase default get_bars_batch falls back to per-symbol calls."""

    def test_fallback_calls_get_bars_per_symbol(self):
        from broker.base import BrokerBase

        class FakeBroker(BrokerBase):
            def get_account(self): ...
            def get_positions(self): ...
            def get_bars(self, symbol, timeframe, limit):
                return _make_bars_df(limit)
            def submit_order(self, *a, **kw): ...
            def cancel_order(self, order_id): ...
            def is_market_open(self): ...
            def get_clock(self): ...

        broker = FakeBroker()
        result = broker.get_bars_batch(["AAPL", "MSFT", "GOOGL"], "1Day", 10)
        assert len(result) == 3
        for sym in ["AAPL", "MSFT", "GOOGL"]:
            assert sym in result
            assert len(result[sym]) == 10


class TestScanUniverseBatched:
    """Test that scan_universe uses batched requests."""

    @patch("config.universe.cfg")
    def test_scan_uses_batches(self, mock_cfg):
        """scan_universe fetches bars in batches, not one-by-one."""
        mock_cfg.CORE_ETFS = ["SPY"]
        mock_cfg.MIN_PRICE = 10.0
        mock_cfg.MIN_DOLLAR_VOLUME = 50_000_000
        mock_cfg.ATR_PERIOD = 20
        mock_cfg.ATR_PCT_MIN = 0.5
        mock_cfg.ATR_PCT_MAX = 8.0
        mock_cfg.DYNAMIC_UNIVERSE_SIZE = 5

        broker = MagicMock()
        # Return bars for every symbol in every batch
        broker.get_bars_batch.return_value = {
            sym: _make_bars_df(252, base_price=200.0)
            for sym in ["AAPL", "MSFT"]  # just need some data
        }

        # Patch SP500_SYMBOLS to a small list
        with patch("config.universe.SP500_SYMBOLS", ["AAPL", "MSFT"]):
            from config.universe import scan_universe
            result = scan_universe(broker)

        # Should have called get_bars_batch (not get_bars)
        broker.get_bars_batch.assert_called()
        broker.get_bars.assert_not_called()

        # SPY should be in the result (core ETF)
        assert "SPY" in result

    @patch("config.universe.cfg")
    def test_scan_batches_multiple_chunks(self, mock_cfg):
        """With many symbols, multiple batch calls are made."""
        mock_cfg.CORE_ETFS = []
        mock_cfg.MIN_PRICE = 0.0
        mock_cfg.MIN_DOLLAR_VOLUME = 0
        mock_cfg.ATR_PERIOD = 20
        mock_cfg.ATR_PCT_MIN = 0.0
        mock_cfg.ATR_PCT_MAX = 100.0
        mock_cfg.DYNAMIC_UNIVERSE_SIZE = 200

        symbols = [f"SYM{i}" for i in range(120)]
        broker = MagicMock()
        broker.get_bars_batch.return_value = {
            sym: _make_bars_df(252, base_price=200.0)
            for sym in symbols
        }

        with patch("config.universe.SP500_SYMBOLS", symbols), \
             patch("config.universe._BATCH_SIZE", 50):
            from config.universe import scan_universe
            result = scan_universe(broker)

        # 120 symbols / 50 per batch = 3 batch calls
        assert broker.get_bars_batch.call_count == 3
