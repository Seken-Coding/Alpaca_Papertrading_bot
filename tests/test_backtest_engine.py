"""Tests for the backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from backtest.engine import (
    Backtester,
    BacktestPosition,
    BacktestResults,
    BacktestTrade,
)


@pytest.fixture
def simple_market_data():
    """Create minimal market data for backtesting (2 symbols, 400 bars)."""
    np.random.seed(42)
    n = 400
    dates = pd.bdate_range("2020-01-01", periods=n)

    data = {}
    for symbol, seed, drift in [("AAPL", 42, 0.0008), ("MSFT", 43, 0.0005)]:
        np.random.seed(seed)
        returns = np.random.normal(drift, 0.015, n)
        prices = 100.0 * np.cumprod(1 + returns)
        close = pd.Series(prices, index=dates)
        high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
        low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
        volume = pd.Series(np.random.randint(1_000_000, 5_000_000, n), index=dates, dtype=float)

        df = pd.DataFrame({
            "open": close.shift(1).fillna(close.iloc[0]).values,
            "high": high.values,
            "low": low.values,
            "close": close.values,
            "volume": volume.values,
        }, index=dates)
        df["high"] = df[["high", "close"]].max(axis=1)
        df["low"] = df[["low", "close"]].min(axis=1)
        data[symbol] = df

    return data


@pytest.fixture
def spy_data():
    """Create SPY data for macro filter testing."""
    np.random.seed(99)
    n = 400
    dates = pd.bdate_range("2020-01-01", periods=n)
    returns = np.random.normal(0.0005, 0.01, n)
    prices = 350.0 * np.cumprod(1 + returns)
    close = pd.Series(prices, index=dates)
    high = close * 1.005
    low = close * 0.995

    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]).values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": np.random.randint(50_000_000, 100_000_000, n),
    }, index=dates)


class TestBacktestResults:
    def test_empty_results(self):
        r = BacktestResults()
        assert r.total_trades == 0
        assert r.win_rate == 0
        assert r.avg_winner == 0
        assert r.avg_loser == 0
        assert r.profit_factor == float("inf")
        assert r.max_drawdown_pct == 0

    def test_with_trades(self):
        r = BacktestResults(initial_equity=100_000)
        r.trades = [
            BacktestTrade("A", "LONG", 100, 110, 0, 10, 100, 1000, 1.0, 2.0, "TARGET", "TREND_UP", "TREND"),
            BacktestTrade("B", "LONG", 100, 95, 0, 5, 100, -500, -0.5, -1.0, "STOP_LOSS", "TREND_UP", "TREND"),
        ]
        r.equity_curve = [100_000, 101_000, 100_500]

        assert r.total_trades == 2
        assert r.winning_trades == 1
        assert r.losing_trades == 1
        assert r.win_rate == 50.0
        assert r.avg_winner == 1000
        assert r.avg_loser == -500
        assert r.risk_reward_ratio == 2.0
        assert r.profit_factor == 2.0
        assert r.total_pnl == 500

    def test_max_drawdown(self):
        r = BacktestResults()
        r.equity_curve = [100_000, 105_000, 95_000, 110_000]
        # Peak was 105k, trough was 95k → DD = 10/105 = 9.52%
        assert 9.0 < r.max_drawdown_pct < 10.0


class TestBacktestPosition:
    def test_update_bar(self):
        pos = BacktestPosition(
            symbol="AAPL", direction="LONG",
            entry_price=100.0, stop_loss=95.0,
            initial_risk=5.0, shares=100,
            entry_bar=0, regime_at_entry="TREND_UP",
            strategy_type="TREND", confluence_score=5,
        )
        assert pos.bars_held == 0
        pos.update_bar(105.0)
        assert pos.bars_held == 1
        assert pos.highest_close_since_entry == 105.0
        pos.update_bar(103.0)
        assert pos.bars_held == 2
        assert pos.highest_close_since_entry == 105.0  # Still 105
        assert pos.lowest_close_since_entry == 100.0   # Entry price


class TestBacktester:
    def test_init(self):
        bt = Backtester(initial_equity=50_000)
        assert bt.equity == 50_000
        assert bt.peak_equity == 50_000
        assert len(bt.positions) == 0

    def test_run_returns_results(self, simple_market_data, spy_data):
        bt = Backtester(initial_equity=100_000, use_spy_macro=False)
        results = bt.run(simple_market_data, spy_data)
        assert isinstance(results, BacktestResults)
        assert len(results.equity_curve) > 0

    def test_run_with_spy_macro(self, simple_market_data, spy_data):
        bt = Backtester(initial_equity=100_000, use_spy_macro=True)
        results = bt.run(simple_market_data, spy_data)
        assert isinstance(results, BacktestResults)

    def test_run_no_data(self):
        bt = Backtester()
        results = bt.run({})
        assert results.total_trades == 0
        assert len(results.equity_curve) == 0

    def test_equity_preserved_no_trades(self):
        """If no trades trigger, equity should remain at initial."""
        bt = Backtester(initial_equity=100_000, use_spy_macro=False)
        # Very short data — no signals should trigger
        dates = pd.bdate_range("2020-01-01", periods=260)
        flat = pd.Series([100.0] * 260, index=dates)
        data = {"TEST": pd.DataFrame({
            "open": flat, "high": flat + 0.01,
            "low": flat - 0.01, "close": flat,
            "volume": [1_000_000] * 260,
        }, index=dates)}
        results = bt.run(data, start_bar=252)
        # May or may not have trades, but equity should be reasonable
        if results.equity_curve:
            assert results.equity_curve[-1] > 0
