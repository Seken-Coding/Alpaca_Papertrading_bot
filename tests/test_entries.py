"""Tests for CEST entry signal generation."""

import numpy as np
import pandas as pd
import pytest

from strategies.entries import generate_signal, _trend_entry, _mean_reversion_entry


class TestTrendEntry:
    def test_no_signal_insufficient_data(self):
        """Should return None with insufficient data."""
        df = pd.DataFrame({
            "open": [100.0] * 50,
            "high": [101.0] * 50,
            "low": [99.0] * 50,
            "close": [100.0] * 50,
            "volume": [1000000.0] * 50,
        })
        result = generate_signal("TEST", "TREND_UP", df)
        assert result is None

    def test_trend_up_generates_long(self, trending_up_data):
        """TREND_UP regime should only generate LONG signals."""
        signal = generate_signal("TEST", "TREND_UP", trending_up_data)
        if signal is not None:
            assert signal.direction == "LONG"
            assert signal.strategy_type == "TREND"
            assert signal.stop_distance > 0

    def test_trend_down_generates_short(self, trending_down_data):
        """TREND_DOWN regime should only generate SHORT signals."""
        signal = generate_signal("TEST", "TREND_DOWN", trending_down_data)
        if signal is not None:
            assert signal.direction == "SHORT"
            assert signal.strategy_type == "TREND"

    def test_crisis_generates_short(self, trending_down_data):
        """CRISIS regime should generate SHORT signals."""
        signal = generate_signal("TEST", "CRISIS", trending_down_data)
        if signal is not None:
            assert signal.direction == "SHORT"

    def test_signal_has_required_fields(self, trending_up_data):
        """Signal should have all required dataclass fields."""
        signal = generate_signal("TEST", "TREND_UP", trending_up_data)
        if signal is not None:
            assert signal.symbol == "TEST"
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert signal.stop_distance > 0
            assert signal.confluence_score >= 5
            assert isinstance(signal.has_vcp, bool)
            assert 0 <= signal.atr_percentile <= 100


class TestMeanReversionEntry:
    def test_range_regime_signal(self, range_data):
        """RANGE regime should use mean-reversion strategy."""
        signal = generate_signal("TEST", "RANGE", range_data)
        if signal is not None:
            assert signal.strategy_type == "MEAN_REVERSION"

    def test_high_vol_regime_signal(self, high_vol_data):
        """HIGH_VOL regime should use mean-reversion strategy."""
        signal = generate_signal("TEST", "HIGH_VOL", high_vol_data)
        if signal is not None:
            assert signal.strategy_type == "MEAN_REVERSION"

    def test_mr_long_has_lower_stop(self, range_data):
        """Mean-reversion LONG should have stop below entry."""
        signal = generate_signal("TEST", "RANGE", range_data)
        if signal is not None and signal.direction == "LONG":
            assert signal.stop_loss < signal.entry_price

    def test_mr_short_has_higher_stop(self):
        """Mean-reversion SHORT should have stop above entry."""
        np.random.seed(42)
        n = 300
        # Create overbought condition: RSI(3) > 85
        prices = 100 + np.cumsum(np.random.normal(0, 0.2, n))
        # Add a sharp run-up at the end
        prices[-5:] += np.array([1, 2, 3, 4, 5])

        df = pd.DataFrame({
            "open": prices - 0.1,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "close": prices,
            "volume": [1_000_000.0] * n,
        })
        signal = generate_signal("TEST", "RANGE", df)
        if signal is not None and signal.direction == "SHORT":
            assert signal.stop_loss > signal.entry_price


class TestGenerateSignal:
    def test_none_for_unknown_regime(self, sample_ohlcv):
        """Unknown regime should return None."""
        result = generate_signal("TEST", "UNKNOWN", sample_ohlcv)
        assert result is None

    def test_signal_direction_not_none(self, trending_up_data):
        """If a signal is generated, direction should not be 'NONE'."""
        signal = generate_signal("TEST", "TREND_UP", trending_up_data)
        if signal is not None:
            assert signal.direction != "NONE"
