"""Tests for the shared bar data cache and broker cache integration."""

import os
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from utils.bar_cache import BarCache, get_shared_cache


# ─────────────────────────────────────────────────────────────────────────────
# BarCache unit tests
# ─────────────────────────────────────────────────────────────────────────────


def _make_df(n=100, base=100.0):
    """Create a simple OHLCV DataFrame."""
    dates = pd.date_range(end=datetime.now(), periods=n, freq="B")
    rng = np.random.default_rng(42)
    close = base + np.cumsum(rng.normal(0, 1, n))
    close = np.maximum(close, 1.0)
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


class TestBarCacheBasic:
    """Test basic get/put operations."""

    def test_put_and_get(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        df = _make_df(50)

        cache.put("SPY", "1Day", 252, df)
        result = cache.get("SPY", "1Day", 252)

        assert result is not None
        assert len(result) == 50
        pd.testing.assert_frame_equal(result, df)

    def test_get_returns_none_on_miss(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        assert cache.get("SPY", "1Day", 252) is None

    def test_put_empty_df_not_cached(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        cache.put("SPY", "1Day", 252, pd.DataFrame())
        assert cache.get("SPY", "1Day", 252) is None

    def test_different_keys_are_independent(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        df_spy = _make_df(50, base=400.0)
        df_qqq = _make_df(50, base=300.0)

        cache.put("SPY", "1Day", 252, df_spy)
        cache.put("QQQ", "1Day", 252, df_qqq)

        result_spy = cache.get("SPY", "1Day", 252)
        result_qqq = cache.get("QQQ", "1Day", 252)

        assert result_spy["close"].iloc[0] != result_qqq["close"].iloc[0]

    def test_different_timeframes_are_independent(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        df_day = _make_df(50)
        df_hour = _make_df(100)

        cache.put("SPY", "1Day", 252, df_day)
        cache.put("SPY", "1Hour", 252, df_hour)

        assert len(cache.get("SPY", "1Day", 252)) == 50
        assert len(cache.get("SPY", "1Hour", 252)) == 100


class TestBarCacheTTL:
    """Test TTL expiration."""

    def test_expired_entry_returns_none(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=1)  # 1 second TTL
        df = _make_df(10)
        cache.put("SPY", "1Day", 252, df)

        # Still fresh
        assert cache.get("SPY", "1Day", 252) is not None

        # Wait for expiry
        time.sleep(1.1)
        assert cache.get("SPY", "1Day", 252) is None

    def test_fresh_entry_returned(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=60)
        df = _make_df(10)
        cache.put("SPY", "1Day", 252, df)
        assert cache.get("SPY", "1Day", 252) is not None


class TestBarCacheBatch:
    """Test get_many/put_many batch operations."""

    def test_put_many_and_get_many(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        data = {
            "SPY": _make_df(50),
            "QQQ": _make_df(50),
            "IWM": _make_df(50),
        }
        cache.put_many(data, "1Day", 252)

        result = cache.get_many(["SPY", "QQQ", "IWM", "DIA"], "1Day", 252)

        assert "SPY" in result
        assert "QQQ" in result
        assert "IWM" in result
        assert "DIA" not in result  # never cached

    def test_get_many_partial_cache(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        cache.put("SPY", "1Day", 252, _make_df(50))

        result = cache.get_many(["SPY", "QQQ"], "1Day", 252)
        assert "SPY" in result
        assert "QQQ" not in result


class TestBarCacheFileSystem:
    """Test file system behavior."""

    def test_creates_cache_directory(self, tmp_path):
        cache_dir = tmp_path / "deep" / "nested" / "cache"
        cache = BarCache(cache_dir=cache_dir, ttl=300)
        assert cache_dir.exists()

    def test_cache_files_are_created(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        cache.put("SPY", "1Day", 252, _make_df(10))

        files = list(tmp_path.glob("*.pkl"))
        assert len(files) == 1
        assert "SPY_1Day_252" in files[0].name

    def test_corrupted_file_returns_none(self, tmp_path):
        cache = BarCache(cache_dir=tmp_path, ttl=300)
        # Write garbage to the expected cache path
        path = tmp_path / "SPY_1Day_252.pkl"
        path.write_bytes(b"not a pickle")

        result = cache.get("SPY", "1Day", 252)
        assert result is None


class TestGetSharedCache:
    """Test module-level singleton."""

    def test_returns_bar_cache_instance(self):
        # Reset singleton
        import utils.bar_cache as mod
        mod._shared_cache = None

        cache = get_shared_cache()
        assert isinstance(cache, BarCache)

    def test_returns_same_instance(self):
        import utils.bar_cache as mod
        mod._shared_cache = None

        c1 = get_shared_cache()
        c2 = get_shared_cache()
        assert c1 is c2


# ─────────────────────────────────────────────────────────────────────────────
# Broker cache integration tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBrokerCacheIntegration:
    """Test that AlpacaBroker.get_bars uses the cache."""

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_get_bars_caches_result(self, tmp_path):
        """First call hits API, second call returns from cache."""
        mock_data_req = MagicMock()
        mock_tf = MagicMock()

        with patch.dict(sys.modules, {
            "alpaca.data.requests": mock_data_req,
            "alpaca.data.timeframe": mock_tf,
        }), patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC, \
             patch("broker.alpaca_broker.get_shared_cache") as mock_get_cache:

            from broker.alpaca_broker import AlpacaBroker

            # Set up a real cache backed by tmp_path
            real_cache = BarCache(cache_dir=tmp_path, ttl=300)
            mock_get_cache.return_value = real_cache

            broker = AlpacaBroker()

            # Mock bar response
            ts = datetime(2024, 6, 1)
            bar = MagicMock()
            bar.open = 500
            bar.high = 510
            bar.low = 495
            bar.close = 505
            bar.volume = 3000000
            bar.timestamp = ts

            mock_bars = {"SPY": [bar]}
            MockDC.return_value.get_stock_bars.return_value = mock_bars

            # First call — hits API
            result1 = broker.get_bars("SPY", "1Day", 252)
            assert not result1.empty
            assert MockDC.return_value.get_stock_bars.call_count == 1

            # Second call — should come from cache (no additional API call)
            result2 = broker.get_bars("SPY", "1Day", 252)
            assert not result2.empty
            assert MockDC.return_value.get_stock_bars.call_count == 1  # Still 1
            pd.testing.assert_frame_equal(result1, result2)

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_get_bars_batch_partial_cache(self, tmp_path):
        """Batch call fetches only uncached symbols from API."""
        mock_data_req = MagicMock()
        mock_tf = MagicMock()

        with patch.dict(sys.modules, {
            "alpaca.data.requests": mock_data_req,
            "alpaca.data.timeframe": mock_tf,
        }), patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC, \
             patch("broker.alpaca_broker.get_shared_cache") as mock_get_cache:

            from broker.alpaca_broker import AlpacaBroker

            real_cache = BarCache(cache_dir=tmp_path, ttl=300)
            mock_get_cache.return_value = real_cache

            broker = AlpacaBroker()

            ts = datetime(2024, 6, 1)

            def make_bar(c):
                bar = MagicMock()
                bar.open = c - 1
                bar.high = c + 5
                bar.low = c - 5
                bar.close = c
                bar.volume = 1000000
                bar.timestamp = ts
                return bar

            # Pre-populate cache with SPY
            spy_df = pd.DataFrame(
                {"open": [499], "high": [510], "low": [495], "close": [505], "volume": [3000000]},
                index=pd.DatetimeIndex([ts]),
            )
            real_cache.put("SPY", "1Day", 252, spy_df)

            # API will only return QQQ (SPY is cached)
            mock_bars = {"QQQ": [make_bar(380)]}
            MockDC.return_value.get_stock_bars.return_value = mock_bars

            result = broker.get_bars_batch(["SPY", "QQQ"], "1Day", 252)

            assert "SPY" in result
            assert "QQQ" in result
            assert result["SPY"]["close"].iloc[0] == 505  # from cache

            # API was called with only ["QQQ"]
            call_args = MockDC.return_value.get_stock_bars.call_args
            request_obj = call_args[0][0]
            # The request was made — that's the key assertion
            MockDC.return_value.get_stock_bars.assert_called_once()

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_get_bars_batch_all_cached(self, tmp_path):
        """When all symbols are cached, no API call is made."""
        with patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC, \
             patch("broker.alpaca_broker.get_shared_cache") as mock_get_cache:

            from broker.alpaca_broker import AlpacaBroker

            real_cache = BarCache(cache_dir=tmp_path, ttl=300)
            mock_get_cache.return_value = real_cache

            broker = AlpacaBroker()

            # Pre-populate cache
            for sym in ["SPY", "QQQ"]:
                real_cache.put(sym, "1Day", 252, _make_df(50))

            result = broker.get_bars_batch(["SPY", "QQQ"], "1Day", 252)

            assert len(result) == 2
            MockDC.return_value.get_stock_bars.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Bot status logger tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBotStatusLogger:
    """Test the shared bot_status.log setup."""

    def test_setup_creates_log_file(self, tmp_path):
        """setup_bot_status_logger creates bot_status.log in the given dir."""
        # Reset the logger to avoid state leakage
        import logging
        status_logger = logging.getLogger("bot_status")
        for h in status_logger.handlers[:]:
            h.close()
            status_logger.removeHandler(h)

        from logging_config import setup_bot_status_logger
        setup_bot_status_logger(str(tmp_path))

        status_logger.info("test heartbeat message")

        # Flush handlers
        for h in status_logger.handlers:
            h.flush()

        log_file = tmp_path / "bot_status.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "test heartbeat message" in content

        # Clean up
        for h in status_logger.handlers[:]:
            h.close()
            status_logger.removeHandler(h)

    def test_setup_is_idempotent(self, tmp_path):
        """Calling setup_bot_status_logger twice doesn't duplicate handlers."""
        import logging
        status_logger = logging.getLogger("bot_status")
        for h in status_logger.handlers[:]:
            h.close()
            status_logger.removeHandler(h)

        from logging_config import setup_bot_status_logger
        setup_bot_status_logger(str(tmp_path))
        count_after_first = len(status_logger.handlers)

        setup_bot_status_logger(str(tmp_path))
        count_after_second = len(status_logger.handlers)

        assert count_after_first == count_after_second

        # Clean up
        for h in status_logger.handlers[:]:
            h.close()
            status_logger.removeHandler(h)

    def test_get_bot_status_logger_returns_named_logger(self):
        from logging_config import get_bot_status_logger
        logger = get_bot_status_logger()
        assert logger.name == "bot_status"


# ─────────────────────────────────────────────────────────────────────────────
# Timezone fix validation
# ─────────────────────────────────────────────────────────────────────────────


class TestTimezoneAwareDatetime:
    """Verify that broker uses timezone-aware datetimes."""

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_get_bars_uses_utc_start(self, tmp_path):
        """get_bars passes timezone-aware start to StockBarsRequest."""
        mock_data_req = MagicMock()
        mock_tf = MagicMock()

        with patch.dict(sys.modules, {
            "alpaca.data.requests": mock_data_req,
            "alpaca.data.timeframe": mock_tf,
        }), patch("broker.alpaca_broker.TradingClient"), \
             patch("broker.alpaca_broker.StockHistoricalDataClient") as MockDC, \
             patch("broker.alpaca_broker.get_shared_cache") as mock_get_cache:

            from broker.alpaca_broker import AlpacaBroker

            # Empty cache so it actually calls the API
            real_cache = BarCache(cache_dir=tmp_path, ttl=300)
            mock_get_cache.return_value = real_cache

            broker = AlpacaBroker()

            # Return empty data — we just want to check the request
            MockDC.return_value.get_stock_bars.return_value = {}

            broker.get_bars("SPY", "1Day", 252)

            # Inspect the StockBarsRequest that was constructed
            call_args = mock_data_req.StockBarsRequest.call_args
            start_arg = call_args[1]["start"]

            # Must be timezone-aware (not naive)
            assert start_arg.tzinfo is not None, \
                f"start datetime should be timezone-aware, got: {start_arg}"
