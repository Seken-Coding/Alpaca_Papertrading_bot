"""CEST indicator functions — pure pandas/numpy, no TA-Lib.

Each function accepts pd.Series and returns pd.Series (or float for scalars).
These are standalone functions used by the CEST strategy modules.
"""

import numpy as np
import pandas as pd


def EMA(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def SMA(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def RSI(series: pd.Series, period: int) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Handle edge cases: all gains → RSI=100, all losses → RSI=0
    rsi = rsi.where(~(avg_loss == 0) | avg_gain.isna(), 100.0)
    rsi = rsi.where(~(avg_gain == 0) | avg_loss.isna(), 0.0)

    return rsi


def ATR(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Average True Range using True Range with EMA smoothing."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def ADX(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Average Directional Index with +DI and -DI calculation."""
    high_diff = high.diff()
    low_diff = -low.diff()

    plus_dm = pd.Series(
        np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0),
        index=high.index,
    )

    # True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    alpha = 1.0 / period
    atr_smooth = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr_smooth.replace(0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr_smooth.replace(0, np.nan)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    return adx


def donchian_high(high: pd.Series, period: int) -> pd.Series:
    """Highest high over rolling window."""
    return high.rolling(window=period).max()


def donchian_low(low: pd.Series, period: int) -> pd.Series:
    """Lowest low over rolling window."""
    return low.rolling(window=period).min()


def bollinger_band_width(close: pd.Series, period: int, std_dev: float) -> pd.Series:
    """Bollinger Band width: (upper - lower) / middle."""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return (upper - lower) / middle.replace(0, np.nan)


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Williams %R oscillator (-100 to 0)."""
    high_max = high.rolling(window=period).max()
    low_min = low.rolling(window=period).min()
    denom = (high_max - low_min).replace(0, np.nan)
    return -100.0 * (high_max - close) / denom


def percentile_rank(value: float, series: pd.Series) -> float:
    """Percentile rank of value within series (0-100)."""
    valid = series.dropna()
    if len(valid) == 0:
        return 50.0
    return float((valid < value).sum()) / len(valid) * 100.0


def volume_sma(volume: pd.Series, period: int) -> pd.Series:
    """Simple moving average of volume."""
    return volume.rolling(window=period).mean()
