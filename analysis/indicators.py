"""Technical indicators computed on OHLCV DataFrames.

Every function takes a DataFrame (with at least 'close', and sometimes
'high', 'low', 'volume' columns) and returns the same DataFrame with
new indicator columns appended.  This keeps the API composable — you can
chain calls:

    df = sma(df, 20)
    df = rsi(df, 14)
    df = macd(df)
"""

import numpy as np
import pandas as pd


# ── Trend ────────────────────────────────────────────────────────────────

def sma(df: pd.DataFrame, period: int, column: str = "close") -> pd.DataFrame:
    """Simple Moving Average."""
    df[f"sma_{period}"] = df[column].rolling(window=period).mean()
    return df


def ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.DataFrame:
    """Exponential Moving Average."""
    df[f"ema_{period}"] = df[column].ewm(span=period, adjust=False).mean()
    return df


# ── Momentum ─────────────────────────────────────────────────────────────

def rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.DataFrame:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = df[column].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    column: str = "close",
) -> pd.DataFrame:
    """MACD line, signal line, and histogram."""
    ema_fast = df[column].ewm(span=fast, adjust=False).mean()
    ema_slow = df[column].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


# ── Volatility ───────────────────────────────────────────────────────────

def bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    num_std: float = 2.0,
    column: str = "close",
) -> pd.DataFrame:
    """Bollinger Bands (middle, upper, lower)."""
    middle = df[column].rolling(window=period).mean()
    std = df[column].rolling(window=period).std()
    df["bb_middle"] = middle
    df["bb_upper"] = middle + num_std * std
    df["bb_lower"] = middle - num_std * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
    return df


def atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return df


# ── Volume ───────────────────────────────────────────────────────────────

def vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Volume-Weighted Average Price (cumulative, intraday-style).

    If the data already has a 'vwap' column from Alpaca we leave it.
    Otherwise we compute it from typical price × volume.
    """
    if "vwap" not in df.columns:
        typical = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()
    return df


def obv(df: pd.DataFrame) -> pd.DataFrame:
    """On-Balance Volume."""
    direction = np.sign(df["close"].diff()).fillna(0)
    df["obv"] = (direction * df["volume"]).cumsum()
    return df


def relative_volume(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Ratio of current volume to its rolling average (RVOL).

    Values > 1 mean above-average activity; > 2 is a volume surge.
    """
    avg = df["volume"].rolling(window=period).mean()
    df["rvol"] = df["volume"] / avg.replace(0, np.nan)
    return df


def mfi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Money Flow Index — volume-weighted RSI."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    raw_mf = typical * df["volume"]
    delta = typical.diff()
    pos_mf = (raw_mf * (delta > 0)).rolling(window=period).sum()
    neg_mf = (raw_mf * (delta < 0)).rolling(window=period).sum()
    ratio = pos_mf / neg_mf.replace(0, np.nan)
    df["mfi"] = 100 - (100 / (1 + ratio))
    return df


# ── Momentum (extended) ──────────────────────────────────────────────────

def stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3,
) -> pd.DataFrame:
    """Stochastic Oscillator (%K and %D)."""
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    denom = (high_max - low_min).replace(0, np.nan)
    df["stoch_k"] = 100 * (df["close"] - low_min) / denom
    df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()
    return df


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index — measures trend strength (0-100)."""
    high_diff = df["high"].diff()
    low_diff = -df["low"].diff()

    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)

    # True Range
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift()).abs()
    tr3 = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    alpha = 1 / period
    atr_s = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=alpha, min_periods=period, adjust=False
    ).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=alpha, min_periods=period, adjust=False
    ).mean() / atr_s.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    return df


def cci(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Commodity Channel Index."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = typical.rolling(window=period).mean()
    mad = typical.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    df["cci"] = (typical - sma_tp) / (0.015 * mad.replace(0, np.nan))
    return df


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Williams %R — momentum oscillator (-100 to 0)."""
    high_max = df["high"].rolling(window=period).max()
    low_min = df["low"].rolling(window=period).min()
    denom = (high_max - low_min).replace(0, np.nan)
    df["williams_r"] = -100 * (high_max - df["close"]) / denom
    return df


def roc(df: pd.DataFrame, period: int = 12, column: str = "close") -> pd.DataFrame:
    """Rate of Change (percentage)."""
    prev = df[column].shift(period)
    df[f"roc_{period}"] = ((df[column] - prev) / prev.replace(0, np.nan)) * 100
    return df


# ── Trend (extended) ─────────────────────────────────────────────────────

def ichimoku(
    df: pd.DataFrame,
    conversion: int = 9,
    base: int = 26,
    leading: int = 52,
    lagging: int = 26,
) -> pd.DataFrame:
    """Ichimoku Kinko Hyo — composite cloud-based trend indicator.

    Columns added:
      ichi_tenkan      – Conversion line (9-period midpoint, fast trend)
      ichi_kijun       – Base line (26-period midpoint, slow trend)
      ichi_cloud_a     – Senkou Span A projected onto current bar
      ichi_cloud_b     – Senkou Span B projected onto current bar
      ichi_cloud_top   – Upper cloud boundary (max of A, B)
      ichi_cloud_bottom– Lower cloud boundary (min of A, B)

    Price above cloud = bullish. Cloud colour (A > B) = additional bias.
    Tenkan crossing above Kijun = bullish TK cross.
    """
    high = df["high"]
    low = df["low"]

    tenkan = (high.rolling(conversion).max() + low.rolling(conversion).min()) / 2
    kijun = (high.rolling(base).max() + low.rolling(base).min()) / 2

    df["ichi_tenkan"] = tenkan
    df["ichi_kijun"] = kijun

    # Senkou spans shifted forward so that at row t the value equals what was
    # computed lagging periods ago — this is the cloud at the current bar.
    df["ichi_cloud_a"] = ((tenkan + kijun) / 2).shift(lagging)
    df["ichi_cloud_b"] = (
        (high.rolling(leading).max() + low.rolling(leading).min()) / 2
    ).shift(lagging)

    df["ichi_cloud_top"] = df[["ichi_cloud_a", "ichi_cloud_b"]].max(axis=1)
    df["ichi_cloud_bottom"] = df[["ichi_cloud_a", "ichi_cloud_b"]].min(axis=1)
    return df


def keltner_channels(
    df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0
) -> pd.DataFrame:
    """Keltner Channels — EMA ± (ATR × multiplier).

    Used together with Bollinger Bands to detect BB/KC squeezes.
    Computes its own ATR if the 'atr' column is not already in *df*.
    """
    if "atr" not in df.columns:
        df = atr(df, 14)
    mid = df["close"].ewm(span=period, adjust=False).mean()
    df["kc_middle"] = mid
    df["kc_upper"] = mid + atr_mult * df["atr"]
    df["kc_lower"] = mid - atr_mult * df["atr"]
    return df


def bb_squeeze(df: pd.DataFrame) -> pd.DataFrame:
    """Detect Bollinger Band / Keltner Channel squeeze.

    A squeeze (True) occurs when the BB is entirely inside the KC —
    indicating price compression before a high-probability directional move.
    Requires bb_upper, bb_lower, kc_upper, kc_lower already in *df*.
    """
    required = {"bb_upper", "bb_lower", "kc_upper", "kc_lower"}
    if not required.issubset(df.columns):
        df["bb_squeeze"] = False
        return df
    df["bb_squeeze"] = (df["bb_upper"] < df["kc_upper"]) & (
        df["bb_lower"] > df["kc_lower"]
    )
    return df


def linear_regression_slope(
    df: pd.DataFrame, period: int = 20, column: str = "close"
) -> pd.DataFrame:
    """OLS regression slope over *period* bars, normalised as % per bar.

    Positive values indicate an upward linear trend; negative downward.
    Normalised by price so the values are comparable across instruments.
    """
    def _slope(arr: np.ndarray) -> float:
        x = np.arange(len(arr))
        return float(np.polyfit(x, arr, 1)[0])

    slopes = df[column].rolling(period).apply(_slope, raw=True)
    df[f"lr_slope_{period}"] = slopes / df[column] * 100
    return df


def historical_volatility(
    df: pd.DataFrame, period: int = 20, column: str = "close"
) -> pd.DataFrame:
    """Annualised historical volatility (%) using log-return standard deviation."""
    log_ret = np.log(df[column] / df[column].shift(1))
    df[f"hv_{period}"] = log_ret.rolling(period).std() * np.sqrt(252) * 100
    return df


# ── Volume (extended) ─────────────────────────────────────────────────────

def chaikin_ad(df: pd.DataFrame) -> pd.DataFrame:
    """Chaikin Accumulation / Distribution Line.

    Measures the cumulative flow of money into or out of a security.
    Rising A/D while price consolidates = stealth accumulation.
    """
    hl_range = (df["high"] - df["low"]).replace(0, np.nan)
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range
    df["chaikin_ad"] = (clv * df["volume"]).cumsum()
    return df


def volume_direction(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Ratio of cumulative up-day volume to down-day volume over *period* bars.

    Values > 1.0 mean buying pressure dominates;
    < 1.0 means selling pressure dominates.
    Unlike RVOL, this captures the *direction* of volume, not just magnitude.
    """
    chg = df["close"].diff()
    up_vol = (df["volume"] * (chg > 0).astype(float)).rolling(period).sum()
    dn_vol = (df["volume"] * (chg < 0).astype(float)).rolling(period).sum()
    df["vol_direction"] = up_vol / dn_vol.replace(0, np.nan)
    return df


def ema_ribbon(
    df: pd.DataFrame,
    periods: list = None,
    column: str = "close",
) -> pd.DataFrame:
    """Multi-EMA ribbon with a 0-100 alignment score.

    Score = 100 → all EMAs in perfect bull order (fastest > … > slowest).
    Score =   0 → all in perfect bear order.
    Score ~  50 → mixed/ranging.

    Adds individual EMA columns if they don't already exist.
    """
    periods = periods or [9, 21, 50, 200]
    for p in periods:
        col = f"ema_{p}"
        if col not in df.columns:
            df[col] = df[column].ewm(span=p, adjust=False).mean()

    sorted_p = sorted(periods)
    pairs = len(sorted_p) - 1
    if pairs > 0:
        bull_pairs = sum(
            (df[f"ema_{sorted_p[i]}"] > df[f"ema_{sorted_p[i + 1]}"]).astype(int)
            for i in range(pairs)
        )
        df["ema_ribbon_score"] = bull_pairs / pairs * 100
    else:
        df["ema_ribbon_score"] = 50.0
    return df


# ── Price-action (extended) ───────────────────────────────────────────────

def donchian_channels(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian Channel — rolling highest high and lowest low.

    A close above dc_upper signals a breakout; a close below dc_lower a breakdown.
    """
    df[f"dc_upper_{period}"] = df["high"].rolling(period).max()
    df[f"dc_lower_{period}"] = df["low"].rolling(period).min()
    df[f"dc_mid_{period}"] = (df[f"dc_upper_{period}"] + df[f"dc_lower_{period}"]) / 2
    return df


def rsi_divergence(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Detect RSI divergence over a rolling *period*-bar window.

    Divergence is one of the most reliable RSI signals:
      +1 = Bullish divergence  (price near period low but RSI recovering ≥8 pts)
      -1 = Bearish divergence  (price near period high but RSI lagging ≥8 pts)
       0 = No divergence

    Requires the 'rsi' column to already be present in *df*.
    """
    if "rsi" not in df.columns or len(df) < period + 2:
        df["rsi_divergence"] = 0
        return df

    close = df["close"]
    rsi_s = df["rsi"]

    p_max = close.rolling(period).max()
    p_min = close.rolling(period).min()
    r_max = rsi_s.rolling(period).max()
    r_min = rsi_s.rolling(period).min()

    # Bearish: price near N-bar high, RSI at least 8 pts below its N-bar peak
    bear = ((close >= p_max * 0.98) & (rsi_s <= r_max - 8)).astype(int) * -1

    # Bullish: price near N-bar low, RSI at least 8 pts above its N-bar trough
    bull = (close <= p_min * 1.02) & (rsi_s >= r_min + 8)

    df["rsi_divergence"] = (bear + bull.astype(int)).clip(-1, 1)
    return df


# ── Price-action helpers ─────────────────────────────────────────────────

def streak(df: pd.DataFrame) -> pd.DataFrame:
    """Count consecutive up/down closes.

    Positive values = consecutive green bars; negative = consecutive red.
    """
    direction = np.sign(df["close"].diff()).fillna(0)
    groups = (direction != direction.shift()).cumsum()
    df["streak"] = direction.groupby(groups).cumsum().fillna(0).astype(int)
    return df


def gap(df: pd.DataFrame) -> pd.DataFrame:
    """Overnight gap percentage (open vs previous close)."""
    prev_close = df["close"].shift()
    df["gap_pct"] = ((df["open"] - prev_close) / prev_close.replace(0, np.nan)) * 100
    return df


# ── Helpers ──────────────────────────────────────────────────────────────

def apply_all(
    df: pd.DataFrame,
    sma_periods: list = None,
    ema_periods: list = None,
    rsi_period: int = 14,
    macd_params: tuple = (12, 26, 9),
    bb_period: int = 20,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Apply the full indicator suite in one call.

    Dependency order is handled internally:
      ATR → Keltner Channels → Bollinger Bands → BB/KC Squeeze
      RSI → RSI Divergence
    """
    sma_periods = sma_periods or [20, 50, 200]
    ema_periods = ema_periods or [9, 21]

    for p in sma_periods:
        df = sma(df, p)
    for p in ema_periods:
        df = ema(df, p)

    df = rsi(df, rsi_period)
    df = macd(df, *macd_params)

    # Volatility — order matters: KC needs ATR; squeeze needs both BB and KC
    df = atr(df, atr_period)
    df = keltner_channels(df)
    df = bollinger_bands(df, bb_period)
    df = bb_squeeze(df)

    # Volume
    df = vwap(df)
    df = obv(df)
    df = relative_volume(df)
    df = mfi(df)
    df = chaikin_ad(df)
    df = volume_direction(df)

    # Momentum (extended)
    df = stochastic(df)
    df = adx(df)
    df = cci(df)
    df = williams_r(df)
    df = roc(df, 12)
    df = roc(df, 5)

    # Trend (extended)
    df = ichimoku(df)
    df = linear_regression_slope(df)
    df = ema_ribbon(df)          # adds ema_50, ema_200 if not already present

    # Price action
    df = streak(df)
    df = gap(df)
    df = donchian_channels(df)

    # Volatility (extended)
    df = historical_volatility(df)

    # Signals (must come after their source indicators)
    df = rsi_divergence(df)      # requires rsi column

    return df
