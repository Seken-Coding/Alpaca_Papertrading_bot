"""Pyramiding Module — Adding to Winners (Jesse Livermore).

Implements Livermore's pyramiding strategy: add to winning positions at
confirmed higher breakout levels, with decreasing size on each addition.

Rules:
  - Only pyramid in TREND_UP or TREND_DOWN regimes
  - Position must be profitable by at least 1R × (pyramid_count + 1)
  - New Donchian breakout must confirm continued trend
  - Max 2 pyramid additions per position
  - Size decreases: 50% of original on 1st add, 30% on 2nd add
  - Move stop to breakeven on each pyramid addition
"""

import logging
from dataclasses import dataclass

import pandas as pd

from analysis.cest_indicators import ATR, donchian_high, donchian_low
from config import cest_settings as cfg

logger = logging.getLogger(__name__)

# Pyramid sizing as fraction of original position
PYRAMID_SIZE_FRACTIONS = [0.50, 0.30]
MAX_PYRAMIDS = 2
PYRAMID_R_THRESHOLD = 1.0  # Must be +1R per pyramid level


@dataclass
class PyramidSignal:
    """Describes a pyramid addition opportunity."""
    symbol: str
    direction: str          # 'LONG' or 'SHORT'
    add_size: int           # shares to add
    new_stop: float         # adjusted stop (breakeven of combined position)
    pyramid_level: int      # 1 or 2 (which addition this is)
    reason: str


def check_pyramid_opportunity(
    trade: "TradeRecord",
    data: pd.DataFrame,
    regime: str,
    equity: float,
) -> PyramidSignal | None:
    """Check if a winning position qualifies for a pyramid addition.

    Parameters
    ----------
    trade  : TradeRecord - the open trade
    data   : pd.DataFrame - OHLCV data
    regime : str - current regime
    equity : float - current account equity

    Returns
    -------
    PyramidSignal or None
    """
    # Only pyramid trend trades
    if trade.strategy_type != "TREND":
        return None

    # Only in trending regimes
    if regime not in ("TREND_UP", "TREND_DOWN"):
        return None

    # Check pyramid count
    pyramids_done = getattr(trade, "pyramids_added", 0)
    if pyramids_done >= MAX_PYRAMIDS:
        return None

    # Must be profitable enough
    is_long = trade.direction == "LONG"
    price = data["close"].iloc[-1]

    if trade.initial_risk <= 0:
        return None

    if is_long:
        current_r = (price - trade.entry_price) / trade.initial_risk
    else:
        current_r = (trade.entry_price - price) / trade.initial_risk

    required_r = PYRAMID_R_THRESHOLD * (pyramids_done + 1)
    if current_r < required_r:
        return None

    # Must have a new Donchian breakout confirming trend continuation
    high = data["high"]
    low = data["low"]
    close = data["close"]

    dc_high = donchian_high(high, cfg.DONCHIAN_PERIOD)
    dc_low = donchian_low(low, cfg.DONCHIAN_PERIOD)

    if is_long:
        prev_dc_high = high.iloc[-(cfg.DONCHIAN_PERIOD + 1):-1].max()
        if price <= prev_dc_high:
            return None  # No new breakout
    else:
        prev_dc_low = low.iloc[-(cfg.DONCHIAN_PERIOD + 1):-1].min()
        if price >= prev_dc_low:
            return None  # No new breakdown

    # Calculate pyramid size
    fraction = PYRAMID_SIZE_FRACTIONS[pyramids_done]
    add_size = max(int(trade.position_size * fraction), 1)

    # New stop: move to breakeven of the combined position
    # (weighted average entry price of original + additions)
    new_stop = trade.entry_price  # breakeven = original entry

    logger.info(
        "PYRAMID opportunity %s %s | Level=%d | Current R=%.1f | "
        "Add %d shares (%.0f%%) | New stop=%.2f (breakeven)",
        trade.direction, trade.symbol, pyramids_done + 1,
        current_r, add_size, fraction * 100, new_stop,
    )

    return PyramidSignal(
        symbol=trade.symbol,
        direction=trade.direction,
        add_size=add_size,
        new_stop=new_stop,
        pyramid_level=pyramids_done + 1,
        reason=f"Pyramid L{pyramids_done + 1}: +{current_r:.1f}R, new breakout",
    )
