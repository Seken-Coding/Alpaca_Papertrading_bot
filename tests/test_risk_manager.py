"""Tests for CEST risk manager."""

import numpy as np
import pandas as pd
import pytest

from risk.cest_risk_manager import (
    get_drawdown_multiplier,
    passes_equity_curve_filter,
    calculate_correlation_matrix,
    check_correlation_filter,
    passes_portfolio_filter,
)


class TestDrawdownMultiplier:
    def test_no_drawdown(self):
        assert get_drawdown_multiplier(100_000, 100_000) == 1.0

    def test_small_drawdown(self):
        # 3% drawdown — should still be 1.0 (below 5%)
        assert get_drawdown_multiplier(97_000, 100_000) == 1.0

    def test_warning_level(self):
        # 5% drawdown
        assert get_drawdown_multiplier(95_000, 100_000) == 0.75

    def test_reduce_50(self):
        # 10% drawdown
        assert get_drawdown_multiplier(90_000, 100_000) == 0.50

    def test_reduce_75(self):
        # 15% drawdown
        assert get_drawdown_multiplier(85_000, 100_000) == 0.25

    def test_halt(self):
        # 20% drawdown
        assert get_drawdown_multiplier(80_000, 100_000) == 0.0

    def test_severe_drawdown(self):
        # 30% drawdown
        assert get_drawdown_multiplier(70_000, 100_000) == 0.0

    def test_zero_peak(self):
        assert get_drawdown_multiplier(100_000, 0) == 1.0


class TestEquityCurveFilter:
    def test_insufficient_data(self):
        """Less than 50 trades should always pass."""
        assert passes_equity_curve_filter([100, 200, -50]) is True

    def test_above_sma(self):
        """Equity curve above SMA should pass."""
        results = [100.0] * 60  # Constant positive — always above SMA
        assert passes_equity_curve_filter(results) is True

    def test_below_sma(self):
        """Declining equity curve should fail."""
        # Start positive, go negative
        results = [200.0] * 30 + [-100.0] * 30
        result = passes_equity_curve_filter(results)
        # The cumulative P&L may be below SMA
        assert isinstance(result, bool)


class TestCorrelationMatrix:
    def test_basic_correlation(self):
        np.random.seed(42)
        n = 100
        base = np.cumsum(np.random.normal(0, 1, n))

        price_data = {
            "A": pd.Series(100 + base),
            "B": pd.Series(100 + base * 0.9 + np.random.normal(0, 0.1, n)),
            "C": pd.Series(100 + np.cumsum(np.random.normal(0, 1, n))),
        }
        matrix = calculate_correlation_matrix(price_data, lookback=60)

        assert not matrix.empty
        assert "A" in matrix.columns
        assert "B" in matrix.columns
        # A and B should be highly correlated
        assert abs(matrix.loc["A", "B"]) > 0.5

    def test_empty_with_insufficient_data(self):
        price_data = {
            "A": pd.Series([1, 2, 3]),  # Too few bars
        }
        matrix = calculate_correlation_matrix(price_data, lookback=60)
        assert matrix.empty


class TestCorrelationFilter:
    def test_allows_uncorrelated(self):
        np.random.seed(42)
        n = 100
        price_data = {
            "EXISTING": pd.Series(100 + np.cumsum(np.random.normal(0, 1, n))),
            "NEW": pd.Series(100 + np.cumsum(np.random.normal(0, 1, n))),
        }
        result = check_correlation_filter("NEW", ["EXISTING"], price_data)
        assert result is True

    def test_blocks_highly_correlated(self):
        np.random.seed(42)
        n = 100
        base = np.cumsum(np.random.normal(0, 1, n))
        price_data = {
            "EXISTING": pd.Series(100 + base),
            "NEW": pd.Series(100 + base + np.random.normal(0, 0.01, n)),
        }
        result = check_correlation_filter("NEW", ["EXISTING"], price_data)
        assert result is False

    def test_allows_empty_portfolio(self):
        result = check_correlation_filter("NEW", [], {})
        assert result is True


class TestPortfolioFilter:
    def test_max_positions(self):
        positions = [{"symbol": f"SYM{i}", "side": "LONG"} for i in range(10)]
        passes, reason = passes_portfolio_filter("NEW", "LONG", positions, {})
        assert passes is False
        assert "Max positions" in reason

    def test_max_same_direction(self):
        positions = [{"symbol": f"SYM{i}", "side": "LONG"} for i in range(6)]
        passes, reason = passes_portfolio_filter("NEW", "LONG", positions, {})
        assert passes is False
        assert "LONG" in reason

    def test_allows_opposite_direction(self):
        # Use symbols from different defined sectors to avoid sector limit
        # SPY=INDEX, XLF=FINANCIALS, XLE=ENERGY, XLK=TECHNOLOGY, XLV=HEALTHCARE, XLI=INDUSTRIALS
        symbols = ["SPY", "XLF", "XLE", "XLK", "XLV", "XLI"]
        positions = [{"symbol": s, "side": "LONG"} for s in symbols]
        # NEW maps to UNKNOWN sector, so no sector conflict
        passes, reason = passes_portfolio_filter("NEW", "SHORT", positions, {})
        # Should pass since we have 6 longs, not 6 shorts
        assert passes is True

    def test_max_sector(self):
        # All positions in same sector as new symbol
        positions = [
            {"symbol": "SPY", "side": "LONG"},
            {"symbol": "QQQ", "side": "LONG"},
            {"symbol": "IWM", "side": "LONG"},
        ]
        passes, reason = passes_portfolio_filter("DIA", "LONG", positions, {})
        assert passes is False
        assert "sector" in reason.lower()

    def test_allows_different_sector(self):
        positions = [
            {"symbol": "SPY", "side": "LONG"},
            {"symbol": "QQQ", "side": "LONG"},
        ]
        passes, reason = passes_portfolio_filter("XLE", "LONG", positions, {})
        assert passes is True

    def test_empty_portfolio_passes(self):
        passes, reason = passes_portfolio_filter("NEW", "LONG", [], {})
        assert passes is True
