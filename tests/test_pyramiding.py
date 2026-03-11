"""Tests for pyramiding (add-to-winners) module."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from strategies.pyramiding import (
    MAX_PYRAMIDS,
    PYRAMID_R_THRESHOLD,
    PYRAMID_SIZE_FRACTIONS,
    PyramidSignal,
    check_pyramid_opportunity,
)


def _make_trade(
    symbol="AAPL",
    direction="LONG",
    entry_price=100.0,
    stop_loss=95.0,
    initial_risk=5.0,
    position_size=100,
    strategy_type="TREND",
    pyramids_added=0,
):
    """Create a mock trade record."""
    trade = MagicMock()
    trade.symbol = symbol
    trade.direction = direction
    trade.entry_price = entry_price
    trade.stop_loss = stop_loss
    trade.initial_risk = initial_risk
    trade.position_size = position_size
    trade.strategy_type = strategy_type
    trade.pyramids_added = pyramids_added
    return trade


def _make_breakout_data(n=300, final_price=115.0):
    """Create OHLCV data with a new Donchian breakout at the end."""
    np.random.seed(42)
    # Trending up data with a breakout at the end
    prices = np.linspace(90, final_price - 2, n - 1)
    prices = np.append(prices, final_price)  # breakout bar
    close = pd.Series(prices)
    high = close + np.abs(np.random.normal(0, 0.3, n))
    low = close - np.abs(np.random.normal(0, 0.3, n))
    volume = pd.Series(np.random.randint(1_000_000, 3_000_000, n), dtype=float)
    df = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]).values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume.values,
    })
    df["high"] = df[["high", "close"]].max(axis=1)
    df["low"] = df[["low", "close"]].min(axis=1)
    return df


def test_no_pyramid_for_mean_reversion():
    """Mean reversion trades should never pyramid."""
    trade = _make_trade(strategy_type="MEAN_REVERSION")
    data = _make_breakout_data()
    result = check_pyramid_opportunity(trade, data, "TREND_UP", 100_000)
    assert result is None


def test_no_pyramid_in_range_regime():
    """Pyramiding should only happen in trending regimes."""
    trade = _make_trade()
    data = _make_breakout_data()
    result = check_pyramid_opportunity(trade, data, "RANGE", 100_000)
    assert result is None


def test_no_pyramid_when_max_reached():
    """Should not pyramid beyond MAX_PYRAMIDS."""
    trade = _make_trade(pyramids_added=MAX_PYRAMIDS)
    data = _make_breakout_data()
    result = check_pyramid_opportunity(trade, data, "TREND_UP", 100_000)
    assert result is None


def test_no_pyramid_when_not_profitable_enough():
    """Position must be profitable by R threshold before pyramiding."""
    # Entry at 100, stop at 95 (risk=5). Price at 103 = 0.6R < 1.0R threshold
    trade = _make_trade(entry_price=100.0, initial_risk=5.0)
    data = _make_breakout_data(final_price=103.0)
    result = check_pyramid_opportunity(trade, data, "TREND_UP", 100_000)
    assert result is None


def test_pyramid_signal_dataclass():
    sig = PyramidSignal(
        symbol="AAPL", direction="LONG",
        add_size=50, new_stop=100.0,
        pyramid_level=1, reason="test",
    )
    assert sig.symbol == "AAPL"
    assert sig.add_size == 50
    assert sig.pyramid_level == 1


def test_pyramid_size_fractions():
    """Verify the pyramid sizing constants are sensible."""
    assert len(PYRAMID_SIZE_FRACTIONS) == MAX_PYRAMIDS
    for frac in PYRAMID_SIZE_FRACTIONS:
        assert 0 < frac < 1.0
    # Each subsequent add should be smaller
    for i in range(1, len(PYRAMID_SIZE_FRACTIONS)):
        assert PYRAMID_SIZE_FRACTIONS[i] < PYRAMID_SIZE_FRACTIONS[i - 1]
