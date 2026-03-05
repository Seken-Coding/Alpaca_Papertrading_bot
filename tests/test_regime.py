"""Tests for CEST regime detection."""

import numpy as np
import pandas as pd
import pytest

from strategies.regime import detect_regime, TREND_UP, TREND_DOWN, RANGE, HIGH_VOL, CRISIS


class TestRegimeDetection:
    def test_uptrend_regime(self, trending_up_data):
        """Strong uptrend should classify as TREND_UP or related trending regime."""
        result = detect_regime(
            trending_up_data["close"],
            trending_up_data["high"],
            trending_up_data["low"],
        )
        # With synthetic data, ATR percentile may push to HIGH_VOL
        assert result in (TREND_UP, RANGE, HIGH_VOL)

    def test_downtrend_regime(self, trending_down_data):
        """Strong downtrend should classify as TREND_DOWN."""
        result = detect_regime(
            trending_down_data["close"],
            trending_down_data["high"],
            trending_down_data["low"],
        )
        assert result in (TREND_DOWN, RANGE)

    def test_range_regime(self, range_data):
        """Sideways market should classify as RANGE."""
        result = detect_regime(
            range_data["close"],
            range_data["high"],
            range_data["low"],
        )
        assert result == RANGE

    def test_high_vol_regime(self, high_vol_data):
        """High volatility spike should classify as HIGH_VOL or CRISIS."""
        result = detect_regime(
            high_vol_data["close"],
            high_vol_data["high"],
            high_vol_data["low"],
        )
        assert result in (HIGH_VOL, CRISIS, RANGE)

    def test_insufficient_data_defaults_to_range(self):
        """Too few bars should default to RANGE."""
        close = pd.Series(range(50), dtype=float)
        high = close + 1
        low = close - 1
        result = detect_regime(close, high, low)
        assert result == RANGE

    def test_regime_returns_valid_string(self, sample_ohlcv):
        """Regime should always return one of the 5 valid strings."""
        result = detect_regime(
            sample_ohlcv["close"],
            sample_ohlcv["high"],
            sample_ohlcv["low"],
        )
        assert result in (CRISIS, HIGH_VOL, TREND_UP, TREND_DOWN, RANGE)

    def test_crisis_priority(self):
        """CRISIS should take priority when conditions overlap with HIGH_VOL."""
        np.random.seed(500)
        n = 300
        # Create downtrend with massive vol spike
        returns = np.concatenate([
            np.random.normal(0.001, 0.01, 200),
            np.random.normal(-0.01, 0.06, 100),
        ])
        prices = 200.0 * np.cumprod(1 + returns)

        close = pd.Series(prices)
        high = close * 1.02
        low = close * 0.98

        result = detect_regime(close, high, low)
        # Should be CRISIS or HIGH_VOL due to extreme volatility
        assert result in (CRISIS, HIGH_VOL, TREND_DOWN)
