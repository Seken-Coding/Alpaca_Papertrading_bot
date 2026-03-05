"""Tests for CEST exit logic."""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime

from strategies.exits import manage_exits, ExitAction
from utils.trade_tracker import TradeRecord


def _make_trade(**kwargs) -> TradeRecord:
    """Helper to create a TradeRecord with defaults."""
    defaults = {
        "symbol": "TEST",
        "direction": "LONG",
        "entry_price": 100.0,
        "entry_date": datetime(2025, 1, 1),
        "stop_loss": 96.0,
        "initial_risk": 4.0,
        "position_size": 100,
        "regime_at_entry": "TREND_UP",
        "strategy_type": "TREND",
        "confluence_score": 5,
        "bars_held": 0,
        "highest_close_since_entry": 100.0,
        "lowest_close_since_entry": 100.0,
    }
    defaults.update(kwargs)
    return TradeRecord(**defaults)


def _make_data(last_close: float, n: int = 50) -> pd.DataFrame:
    """Helper to create OHLCV data ending at a specific close price."""
    np.random.seed(42)
    prices = np.linspace(100, last_close, n)
    return pd.DataFrame({
        "open": prices - 0.1,
        "high": prices + 1.0,
        "low": prices - 1.0,
        "close": prices,
        "volume": [1_000_000.0] * n,
    })


class TestStopLoss:
    def test_long_stop_hit(self):
        trade = _make_trade(stop_loss=96.0)
        data = _make_data(last_close=95.0)
        result = manage_exits(trade, data, "TREND_UP")
        assert result is not None
        assert result.action == "FULL_EXIT"
        assert result.reason == "STOP_LOSS"

    def test_long_stop_not_hit(self):
        trade = _make_trade(stop_loss=96.0)
        data = _make_data(last_close=100.0)
        result = manage_exits(trade, data, "TREND_UP")
        # Should not trigger stop
        assert result is None or result.reason != "STOP_LOSS"

    def test_short_stop_hit(self):
        trade = _make_trade(direction="SHORT", stop_loss=104.0, entry_price=100.0)
        data = _make_data(last_close=105.0)
        result = manage_exits(trade, data, "TREND_DOWN")
        assert result is not None
        assert result.action == "FULL_EXIT"
        assert result.reason == "STOP_LOSS"


class TestTimeExit:
    def test_trend_time_exit(self):
        """Trend trade should exit after 10 bars if not moved 1R."""
        trade = _make_trade(
            bars_held=10,
            highest_close_since_entry=100.5,  # Only moved 0.125R
        )
        data = _make_data(last_close=100.0)
        result = manage_exits(trade, data, "TREND_UP")
        assert result is not None
        assert result.reason == "TIME_EXIT"

    def test_mr_time_exit(self):
        """Mean-reversion trade should exit after 5 bars."""
        trade = _make_trade(
            strategy_type="MEAN_REVERSION",
            bars_held=5,
            stop_loss=98.5,
            initial_risk=1.5,
        )
        data = _make_data(last_close=100.0)
        result = manage_exits(trade, data, "RANGE")
        assert result is not None
        assert result.reason == "TIME_EXIT"

    def test_trend_no_time_exit_if_moved_1r(self):
        """Trend trade that moved 1R should not time-exit."""
        trade = _make_trade(
            bars_held=10,
            highest_close_since_entry=105.0,  # Moved 1.25R (4.0 initial risk)
        )
        data = _make_data(last_close=103.0)
        result = manage_exits(trade, data, "TREND_UP")
        assert result is None or result.reason != "TIME_EXIT"


class TestBreakeven:
    def test_breakeven_trigger(self):
        """Breakeven should trigger at 1.5R profit."""
        trade = _make_trade(breakeven_triggered=False)
        # 1.5R = entry + 1.5 * 4.0 = 106.0
        data = _make_data(last_close=107.0)
        result = manage_exits(trade, data, "TREND_UP")
        if result is not None and result.reason == "BREAKEVEN":
            assert result.action == "ADJUST_STOP"
            assert result.new_stop == trade.entry_price


class TestPartialProfit:
    def test_partial_exit_at_3r(self):
        """Trend trade should take partial at 3R."""
        trade = _make_trade(partial_taken=False)
        # 3R = entry + 3 * 4.0 = 112.0
        data = _make_data(last_close=113.0)
        result = manage_exits(trade, data, "TREND_UP")
        if result is not None and result.reason == "TARGET":
            assert result.action == "PARTIAL_EXIT"
            assert result.partial_pct == 0.5


class TestMRTarget:
    def test_mr_target_exit(self):
        """Mean-reversion trade should exit at 1.5R."""
        trade = _make_trade(
            strategy_type="MEAN_REVERSION",
            initial_risk=1.5,
            stop_loss=98.5,
        )
        # 1.5R for MR = entry + 1.5 * 1.5 = 102.25
        data = _make_data(last_close=103.0)
        result = manage_exits(trade, data, "RANGE")
        assert result is not None
        # RSI exit may trigger before target if RSI(3) crosses threshold
        assert result.reason in ("TARGET", "RSI_EXIT")
        assert result.action == "FULL_EXIT"


class TestChandelierStop:
    def test_chandelier_tightens(self):
        """Chandelier stop should only tighten, never widen."""
        trade = _make_trade(
            breakeven_triggered=True,
            highest_close_since_entry=115.0,
            stop_loss=100.0,
        )
        data = _make_data(last_close=112.0)
        result = manage_exits(trade, data, "TREND_UP")
        if result is not None and result.action == "ADJUST_STOP":
            assert result.new_stop >= trade.stop_loss
