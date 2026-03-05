"""Tests for CEST position sizing."""

import pytest

from risk.position_sizing import calculate_position_size


class TestPositionSizing:
    def test_basic_sizing(self):
        """Basic 1% risk sizing."""
        shares = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        # Risk = $1000, stop_dist = $2 → base = 500 shares
        # conviction (6, no vcp) = 1.0, vol (50 pctile) = 1.0, regime = 1.0
        assert shares == 500

    def test_max_risk_cap(self):
        """Position size should not exceed 2% max risk."""
        shares = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=0.5,  # Very tight stop → large position
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=True,
            atr_percentile=10,
            drawdown_multiplier=1.0,
        )
        # Max at 2%: 100000 * 0.02 / 0.5 = 4000 shares
        assert shares <= 4000

    def test_conviction_low_score(self):
        """Confluence score of 5 should reduce size by 25%."""
        shares_5 = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=5,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        shares_6 = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        assert shares_5 < shares_6  # 0.75x vs 1.0x

    def test_conviction_vcp_bonus(self):
        """VCP with score >= 6 should get 1.25x bonus."""
        shares_no_vcp = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        shares_vcp = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=True,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        assert shares_vcp > shares_no_vcp

    def test_high_volatility_reduces_size(self):
        """High ATR percentile should reduce position size."""
        shares_low = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=20,
            drawdown_multiplier=1.0,
        )
        shares_high = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=85,
            drawdown_multiplier=1.0,
        )
        assert shares_high < shares_low

    def test_regime_multiplier(self):
        """RANGE and HIGH_VOL regimes should reduce size."""
        shares_trend = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        shares_range = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="RANGE",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        assert shares_range == shares_trend // 2  # 0.5x

    def test_drawdown_multiplier(self):
        """Drawdown should scale down position size."""
        shares_full = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        shares_half = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=0.5,
        )
        assert shares_half == shares_full // 2

    def test_minimum_one_share(self):
        """Should always return at least 1 share."""
        shares = calculate_position_size(
            equity=100,
            entry_price=1000,
            stop_distance=100.0,
            regime="CRISIS",
            confluence_score=5,
            has_vcp=False,
            atr_percentile=95,
            drawdown_multiplier=0.25,
        )
        assert shares >= 1

    def test_zero_equity(self):
        """Zero equity should return 1 (minimum)."""
        shares = calculate_position_size(
            equity=0,
            entry_price=100,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        assert shares == 1

    def test_zero_stop_distance(self):
        """Zero stop distance should return 1 (minimum)."""
        shares = calculate_position_size(
            equity=100_000,
            entry_price=100,
            stop_distance=0,
            regime="TREND_UP",
            confluence_score=6,
            has_vcp=False,
            atr_percentile=50,
            drawdown_multiplier=1.0,
        )
        assert shares == 1
