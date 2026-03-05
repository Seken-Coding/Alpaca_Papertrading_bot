"""CEST Entry Signal Generation.

Generates entry signals based on regime:
  - Trend-following entries (TREND_UP: longs, TREND_DOWN: shorts)
  - Mean-reversion entries (RANGE, HIGH_VOL)
  - CRISIS: emergency shorts only

All signals include confluence scoring and mandatory correlation filtering.
"""

import logging
from dataclasses import dataclass

import pandas as pd

from analysis.cest_indicators import (
    ATR,
    EMA,
    RSI,
    SMA,
    bollinger_band_width,
    donchian_high,
    donchian_low,
    percentile_rank,
    volume_sma,
    ADX,
)
from config import cest_settings as cfg
from strategies.patterns import detect_vcp
from strategies.regime import (
    CRISIS,
    HIGH_VOL,
    RANGE,
    REGIME_MR_ACTIVE,
    REGIME_TREND_ACTIVE,
    TREND_DOWN,
    TREND_UP,
)

logger = logging.getLogger(__name__)


@dataclass
class EntrySignal:
    """Represents a potential entry signal."""
    symbol: str
    direction: str          # 'LONG', 'SHORT', or 'NONE'
    strategy_type: str      # 'TREND' or 'MEAN_REVERSION'
    entry_price: float
    stop_loss: float
    stop_distance: float    # abs(entry - stop) per share
    confluence_score: int   # number of conditions met
    has_vcp: bool
    atr_percentile: float
    regime: str
    reason: str


def generate_signal(
    symbol: str,
    regime: str,
    data: pd.DataFrame,
) -> EntrySignal | None:
    """Generate an entry signal for a symbol based on its regime.

    Parameters
    ----------
    symbol : str - ticker symbol
    regime : str - current regime classification
    data   : pd.DataFrame - OHLCV data with columns: open, high, low, close, volume

    Returns
    -------
    EntrySignal or None if no valid signal
    """
    if len(data) < cfg.VOL_LOOKBACK:
        return None

    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    if regime in REGIME_TREND_ACTIVE:
        return _trend_entry(symbol, regime, close, high, low, volume)
    elif regime in REGIME_MR_ACTIVE:
        return _mean_reversion_entry(symbol, regime, close, high, low, volume)

    return None


def _trend_entry(
    symbol: str,
    regime: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> EntrySignal | None:
    """Trend-following entry (3A for longs, 3B for shorts)."""
    is_long = regime in (TREND_UP,)
    is_short = regime in (TREND_DOWN, CRISIS)

    if not is_long and not is_short:
        return None

    price = close.iloc[-1]

    # Compute indicators
    atr_series = ATR(high, low, close, period=cfg.ATR_PERIOD)
    atr_val = atr_series.iloc[-1]
    if pd.isna(atr_val) or atr_val <= 0:
        return None

    atr_pctile = percentile_rank(atr_val, atr_series.tail(cfg.VOL_LOOKBACK))

    ema_fast = EMA(close, cfg.EMA_FAST)
    ema_slow = EMA(close, cfg.EMA_SLOW)
    rsi_series = RSI(close, cfg.RSI_PERIOD)
    rsi_val = rsi_series.iloc[-1]
    vol_sma = volume_sma(volume, cfg.VOLUME_SMA_PERIOD)
    dc_high = donchian_high(high, cfg.DONCHIAN_PERIOD)
    dc_low = donchian_low(low, cfg.DONCHIAN_PERIOD)

    conditions_met = 0
    reasons = []

    if is_long:
        # Condition 1: Price closes above highest high of last 20 bars
        # Use shifted donchian to compare against prior bars (not including current)
        prev_dc_high = high.iloc[-(cfg.DONCHIAN_PERIOD + 1):-1].max()
        if price > prev_dc_high:
            conditions_met += 1
            reasons.append("Donchian breakout")

        # Condition 2: EMA(10) > EMA(21)
        if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
            conditions_met += 1
            reasons.append("EMA alignment")

        # Condition 3: RSI(14) between 50 and 80
        if not pd.isna(rsi_val) and cfg.RSI_TREND_LOW <= rsi_val <= cfg.RSI_TREND_HIGH:
            conditions_met += 1
            reasons.append(f"RSI={rsi_val:.0f}")

        # Condition 4: Volume > 1.5x SMA(volume, 20)
        vol_threshold = vol_sma.iloc[-1] * cfg.VOLUME_BREAKOUT_MULTIPLIER
        if not pd.isna(vol_threshold) and volume.iloc[-1] > vol_threshold:
            conditions_met += 1
            reasons.append("Volume surge")

        # Condition 5: ATR percentile between 10 and 75
        if 10 <= atr_pctile <= 75:
            conditions_met += 1
            reasons.append(f"ATR pctile={atr_pctile:.0f}")

        # Condition 6: VCP (optional bonus)
        has_vcp = detect_vcp(close, volume)
        if has_vcp:
            conditions_met += 1
            reasons.append("VCP")

        # Need at least 5 of conditions 1-5 (condition 6 is bonus)
        base_score = min(conditions_met, 5) if not has_vcp else conditions_met
        if conditions_met < cfg.MIN_CONFLUENCE_SCORE:
            return None

        stop_loss = price - cfg.TREND_STOP_ATR_MULT * atr_val
        direction = "LONG"

    else:  # SHORT
        # Condition 1: Price closes below lowest low of last 20 bars
        prev_dc_low = low.iloc[-(cfg.DONCHIAN_PERIOD + 1):-1].min()
        if price < prev_dc_low:
            conditions_met += 1
            reasons.append("Donchian breakdown")

        # Condition 2: EMA(10) < EMA(21)
        if ema_fast.iloc[-1] < ema_slow.iloc[-1]:
            conditions_met += 1
            reasons.append("EMA alignment (bearish)")

        # Condition 3: RSI(14) between 20 and 50
        if not pd.isna(rsi_val) and 20 <= rsi_val <= cfg.RSI_TREND_LOW:
            conditions_met += 1
            reasons.append(f"RSI={rsi_val:.0f}")

        # Condition 4: Volume surge
        vol_threshold = vol_sma.iloc[-1] * cfg.VOLUME_BREAKOUT_MULTIPLIER
        if not pd.isna(vol_threshold) and volume.iloc[-1] > vol_threshold:
            conditions_met += 1
            reasons.append("Volume surge")

        # Condition 5: ATR percentile between 10 and 75
        if 10 <= atr_pctile <= 75:
            conditions_met += 1
            reasons.append(f"ATR pctile={atr_pctile:.0f}")

        has_vcp = False  # No VCP for shorts

        if conditions_met < cfg.MIN_CONFLUENCE_SCORE:
            return None

        stop_loss = price + cfg.TREND_STOP_ATR_MULT * atr_val
        direction = "SHORT"

    stop_distance = abs(price - stop_loss)

    logger.info(
        "TREND signal %s %s | Regime=%s | Confluence=%d | %s",
        direction, symbol, regime, conditions_met, ", ".join(reasons),
    )

    return EntrySignal(
        symbol=symbol,
        direction=direction,
        strategy_type="TREND",
        entry_price=price,
        stop_loss=stop_loss,
        stop_distance=stop_distance,
        confluence_score=conditions_met,
        has_vcp=has_vcp,
        atr_percentile=atr_pctile,
        regime=regime,
        reason="; ".join(reasons),
    )


def _mean_reversion_entry(
    symbol: str,
    regime: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> EntrySignal | None:
    """Mean-reversion entry (RANGE or HIGH_VOL regime).

    ALL 5 conditions must be TRUE.
    """
    price = close.iloc[-1]

    # Compute indicators
    rsi3 = RSI(close, cfg.RSI_SHORT_PERIOD)
    rsi3_val = rsi3.iloc[-1]
    if pd.isna(rsi3_val):
        return None

    ema20 = EMA(close, cfg.BB_PERIOD)
    ema20_val = ema20.iloc[-1]

    adx_series = ADX(high, low, close, period=cfg.ADX_PERIOD)
    adx_val = adx_series.iloc[-1]
    if pd.isna(adx_val):
        return None

    bb_width = bollinger_band_width(close, cfg.BB_PERIOD, cfg.BB_STD)
    bb_width_current = bb_width.iloc[-1]
    bb_width_history = bb_width.tail(100)
    if pd.isna(bb_width_current) or len(bb_width_history.dropna()) < 20:
        return None
    bb_width_pctile = percentile_rank(bb_width_current, bb_width_history)

    atr_series = ATR(high, low, close, period=cfg.ATR_PERIOD)
    atr_val = atr_series.iloc[-1]
    if pd.isna(atr_val) or atr_val <= 0:
        return None
    atr_pctile = percentile_rank(atr_val, atr_series.tail(cfg.VOL_LOOKBACK))

    # Determine direction from RSI(3)
    is_long = rsi3_val < cfg.RSI_MR_OVERSOLD
    is_short = rsi3_val > cfg.RSI_MR_OVERBOUGHT

    if not is_long and not is_short:
        return None

    # Check all 5 conditions
    conditions_met = 0
    reasons = []

    # Condition 1: RSI(3) extremes (already checked above)
    conditions_met += 1
    reasons.append(f"RSI(3)={rsi3_val:.0f}")

    # Condition 2: Price within 2% of EMA(20)
    if ema20_val > 0:
        distance_pct = abs(price - ema20_val) / ema20_val * 100.0
        if distance_pct <= cfg.MR_DISTANCE_FROM_MEAN_PCT:
            conditions_met += 1
            reasons.append(f"Near EMA20 ({distance_pct:.1f}%)")

    # Condition 3: ADX(14) < 20
    if adx_val < cfg.ADX_RANGE_THRESHOLD:
        conditions_met += 1
        reasons.append(f"ADX={adx_val:.0f}")

    # Condition 4: BB width below 25th percentile
    if bb_width_pctile < cfg.BB_WIDTH_PERCENTILE:
        conditions_met += 1
        reasons.append(f"BB narrow (pctile={bb_width_pctile:.0f})")

    # Condition 5: Correlation filter (checked externally, count as met here)
    # The correlation filter is mandatory and checked in the main loop
    conditions_met += 1
    reasons.append("Corr filter (pending)")

    # ALL 5 must be true
    if conditions_met < 5:
        return None

    if is_long:
        stop_loss = price - cfg.MR_STOP_ATR_MULT * atr_val
        direction = "LONG"
    else:
        stop_loss = price + cfg.MR_STOP_ATR_MULT * atr_val
        direction = "SHORT"

    stop_distance = abs(price - stop_loss)

    logger.info(
        "MR signal %s %s | Regime=%s | %s",
        direction, symbol, regime, ", ".join(reasons),
    )

    return EntrySignal(
        symbol=symbol,
        direction=direction,
        strategy_type="MEAN_REVERSION",
        entry_price=price,
        stop_loss=stop_loss,
        stop_distance=stop_distance,
        confluence_score=conditions_met,
        has_vcp=False,
        atr_percentile=atr_pctile,
        regime=regime,
        reason="; ".join(reasons),
    )
