"""CEST Regime Detection Module.

Classifies each instrument's market regime on every daily bar close.
Uses EMA(200) slope, ADX(14), and ATR percentile to determine the active regime.

Regime determines which sub-strategy is active:
  TREND_UP  → Trend-following (longs only), size 1.0×
  TREND_DOWN → Trend-following (shorts only), size 1.0×
  RANGE     → Mean-reversion, size 0.5×
  HIGH_VOL  → Mean-reversion, size 0.25×
  CRISIS    → Emergency shorts only, size 0.25×
"""

import logging

import pandas as pd

from analysis.cest_indicators import ADX, ATR, EMA, percentile_rank
from config.cest_settings import (
    ADX_PERIOD,
    ADX_RANGE_THRESHOLD,
    ADX_TREND_THRESHOLD,
    ATR_PERIOD,
    EMA_REGIME,
    EMA_SLOPE_THRESHOLD,
    VOL_LOOKBACK,
    VOL_PERCENTILE_CRISIS,
    VOL_PERCENTILE_HIGH,
)

logger = logging.getLogger(__name__)

# Regime constants
CRISIS = "CRISIS"
HIGH_VOL = "HIGH_VOL"
TREND_UP = "TREND_UP"
TREND_DOWN = "TREND_DOWN"
RANGE = "RANGE"

# Regime → size multiplier mapping
REGIME_SIZE_MULTIPLIER = {
    TREND_UP: 1.0,
    TREND_DOWN: 1.0,
    RANGE: 0.5,
    HIGH_VOL: 0.25,
    CRISIS: 0.25,
}

# Regime → allowed strategies
REGIME_TREND_ACTIVE = {TREND_UP, TREND_DOWN, CRISIS}
REGIME_MR_ACTIVE = {RANGE, HIGH_VOL}


def detect_regime(close: pd.Series, high: pd.Series, low: pd.Series) -> str:
    """Classify the current market regime for an instrument.

    Priority: CRISIS > HIGH_VOL > TREND_UP/TREND_DOWN > RANGE

    Parameters
    ----------
    close : pd.Series - daily close prices (need ≥252 bars ideally)
    high  : pd.Series - daily high prices
    low   : pd.Series - daily low prices

    Returns
    -------
    str : one of 'CRISIS', 'HIGH_VOL', 'TREND_UP', 'TREND_DOWN', 'RANGE'
    """
    if len(close) < EMA_REGIME + 21:
        logger.warning(
            "Insufficient data for regime detection (%d bars, need %d). Defaulting to RANGE.",
            len(close),
            EMA_REGIME + 21,
        )
        return RANGE

    # Input 1: Slope of 200 EMA (% change per bar over last 20 bars)
    ema200 = EMA(close, EMA_REGIME)
    ema200_val = ema200.iloc[-1]
    ema200_20ago = ema200.iloc[-21]
    if ema200_20ago == 0 or pd.isna(ema200_20ago) or pd.isna(ema200_val):
        return RANGE
    ema200_slope = (ema200_val - ema200_20ago) / ema200_20ago * 100.0 / 20.0

    # Input 2: ADX(14)
    adx_series = ADX(high, low, close, period=ADX_PERIOD)
    adx_val = adx_series.iloc[-1]
    if pd.isna(adx_val):
        adx_val = 0.0

    # Input 3: ATR percentile (current ATR(20) ranked vs trailing 252 days)
    atr_series = ATR(high, low, close, period=ATR_PERIOD)
    atr_current = atr_series.iloc[-1]
    if pd.isna(atr_current):
        return RANGE

    atr_history = atr_series.tail(VOL_LOOKBACK)
    vol_pctile = percentile_rank(atr_current, atr_history)

    price = close.iloc[-1]

    # Classification (priority-ordered)
    if vol_pctile > VOL_PERCENTILE_CRISIS and price < ema200_val and adx_val > ADX_TREND_THRESHOLD + 5:
        return CRISIS

    if vol_pctile > VOL_PERCENTILE_HIGH:
        return HIGH_VOL

    if ema200_slope > EMA_SLOPE_THRESHOLD and adx_val > ADX_TREND_THRESHOLD and price > ema200_val:
        return TREND_UP

    if ema200_slope < -EMA_SLOPE_THRESHOLD and adx_val > ADX_TREND_THRESHOLD and price < ema200_val:
        return TREND_DOWN

    return RANGE
