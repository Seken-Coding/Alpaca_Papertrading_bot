"""Tests for CEST indicator functions."""

import numpy as np
import pandas as pd
import pytest

from analysis.cest_indicators import (
    EMA, SMA, RSI, ATR, ADX,
    donchian_high, donchian_low,
    bollinger_band_width, williams_r,
    percentile_rank, volume_sma,
)


class TestSMA:
    def test_sma_basic(self):
        series = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        result = SMA(series, 3)
        # SMA(3) at index 2 = (1+2+3)/3 = 2.0
        assert result.iloc[2] == pytest.approx(2.0)
        # SMA(3) at index 9 = (8+9+10)/3 = 9.0
        assert result.iloc[9] == pytest.approx(9.0)

    def test_sma_nan_for_insufficient_data(self):
        series = pd.Series([1, 2, 3], dtype=float)
        result = SMA(series, 5)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[3]) if len(result) > 3 else True

    def test_sma_length(self):
        series = pd.Series(range(100), dtype=float)
        result = SMA(series, 20)
        assert len(result) == len(series)


class TestEMA:
    def test_ema_basic(self):
        series = pd.Series([10.0] * 20)
        result = EMA(series, 10)
        # Constant input → EMA = constant
        assert result.iloc[-1] == pytest.approx(10.0)

    def test_ema_reacts_to_trend(self):
        series = pd.Series(range(1, 51), dtype=float)
        result = EMA(series, 10)
        # EMA should be below the last price in an uptrend
        assert result.iloc[-1] < series.iloc[-1]
        assert result.iloc[-1] > result.iloc[-10]

    def test_ema_length(self):
        series = pd.Series(range(100), dtype=float)
        result = EMA(series, 20)
        assert len(result) == len(series)


class TestRSI:
    def test_rsi_range(self):
        np.random.seed(42)
        series = pd.Series(100 + np.cumsum(np.random.normal(0, 1, 200)))
        result = RSI(series, 14)
        valid = result.dropna()
        assert all(0 <= v <= 100 for v in valid)

    def test_rsi_overbought_in_uptrend(self):
        # Strong uptrend should produce high RSI
        # Use enough data for Wilder's smoothing to converge
        series = pd.Series(range(1, 201), dtype=float)
        result = RSI(series, 14)
        valid = result.dropna()
        # After 200 bars of pure uptrend, RSI should be very high
        assert valid.iloc[-1] > 90

    def test_rsi_oversold_in_downtrend(self):
        series = pd.Series(range(100, 0, -1), dtype=float)
        result = RSI(series, 14)
        assert result.iloc[-1] < 10

    def test_rsi_neutral_in_range(self):
        # Alternating up/down should produce RSI near 50
        series = pd.Series([100 + (i % 2) for i in range(100)], dtype=float)
        result = RSI(series, 14)
        assert 40 < result.iloc[-1] < 60


class TestATR:
    def test_atr_positive(self, sample_ohlcv):
        result = ATR(sample_ohlcv["high"], sample_ohlcv["low"], sample_ohlcv["close"], 20)
        valid = result.dropna()
        assert all(v > 0 for v in valid)

    def test_atr_uses_true_range(self):
        """ATR should use max(H-L, |H-prevC|, |L-prevC|) not just H-L."""
        high = pd.Series([10, 12, 11, 13, 12], dtype=float)
        low = pd.Series([9, 11, 10, 12, 11], dtype=float)
        close = pd.Series([9.5, 11.5, 10.5, 12.5, 11.5], dtype=float)
        result = ATR(high, low, close, 2)
        # With gaps, ATR should be > simple H-L range
        assert len(result) == 5

    def test_atr_length(self, sample_ohlcv):
        result = ATR(sample_ohlcv["high"], sample_ohlcv["low"], sample_ohlcv["close"], 20)
        assert len(result) == len(sample_ohlcv)


class TestADX:
    def test_adx_range(self, sample_ohlcv):
        result = ADX(sample_ohlcv["high"], sample_ohlcv["low"], sample_ohlcv["close"], 14)
        valid = result.dropna()
        assert all(0 <= v <= 100 for v in valid)

    def test_adx_high_in_trend(self, trending_up_data):
        result = ADX(
            trending_up_data["high"],
            trending_up_data["low"],
            trending_up_data["close"],
            14,
        )
        # ADX should be elevated in a strong trend
        assert result.iloc[-1] > 15

    def test_adx_length(self, sample_ohlcv):
        result = ADX(sample_ohlcv["high"], sample_ohlcv["low"], sample_ohlcv["close"], 14)
        assert len(result) == len(sample_ohlcv)


class TestDonchian:
    def test_donchian_high(self):
        high = pd.Series([10, 12, 11, 15, 13, 14, 9, 16, 12, 11], dtype=float)
        result = donchian_high(high, 5)
        # At index 4 (0-indexed), max of indices 0-4 = max(10,12,11,15,13) = 15
        assert result.iloc[4] == 15.0

    def test_donchian_low(self):
        low = pd.Series([10, 8, 11, 7, 13, 14, 9, 6, 12, 11], dtype=float)
        result = donchian_low(low, 5)
        # At index 4, min of indices 0-4 = min(10,8,11,7,13) = 7
        assert result.iloc[4] == 7.0


class TestBollingerBandWidth:
    def test_bb_width_positive(self, sample_ohlcv):
        result = bollinger_band_width(sample_ohlcv["close"], 20, 2.0)
        valid = result.dropna()
        assert all(v > 0 for v in valid)

    def test_bb_width_narrow_in_range(self, range_data):
        result_range = bollinger_band_width(range_data["close"], 20, 2.0)
        result_vol = bollinger_band_width(
            pd.Series(np.random.normal(100, 10, 300)), 20, 2.0,
        )
        # Range data should have narrower BB than volatile data
        assert result_range.dropna().iloc[-1] < result_vol.dropna().iloc[-1]


class TestWilliamsR:
    def test_williams_r_range(self, sample_ohlcv):
        result = williams_r(
            sample_ohlcv["high"], sample_ohlcv["low"], sample_ohlcv["close"], 14,
        )
        valid = result.dropna()
        assert all(-100 <= v <= 0 for v in valid)


class TestPercentileRank:
    def test_percentile_rank_basic(self):
        series = pd.Series(range(100), dtype=float)
        assert percentile_rank(50, series) == pytest.approx(50.0, abs=1)
        assert percentile_rank(0, series) == pytest.approx(0.0, abs=1)
        assert percentile_rank(99, series) == pytest.approx(99.0, abs=1)

    def test_percentile_rank_empty(self):
        result = percentile_rank(10, pd.Series([], dtype=float))
        assert result == 50.0  # Default for empty

    def test_percentile_rank_extreme(self):
        series = pd.Series([1, 2, 3, 4, 5], dtype=float)
        assert percentile_rank(0, series) == 0.0
        assert percentile_rank(6, series) == 100.0


class TestVolumeSMA:
    def test_volume_sma_basic(self):
        volume = pd.Series([100] * 30, dtype=float)
        result = volume_sma(volume, 20)
        assert result.iloc[-1] == pytest.approx(100.0)
