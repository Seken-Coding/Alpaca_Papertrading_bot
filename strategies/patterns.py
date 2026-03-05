"""CEST Pattern Detection — Volatility Contraction Pattern (VCP).

Implements Mark Minervini's VCP detection:
  - 3+ pullbacks where each is shallower than the prior
  - Declining volume through the pattern
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Pullback:
    """Represents a single pullback within a VCP."""
    start_idx: int
    end_idx: int
    high_price: float
    low_price: float
    depth_pct: float  # % decline from local high to local low


def identify_pullbacks(close: pd.Series, lookback: int = 60) -> list[Pullback]:
    """Identify pullback swings within the lookback window.

    A pullback is defined as a move from a local high to a local low,
    where local extremes are identified using a simple swing detection.
    """
    if len(close) < lookback:
        return []

    prices = close.iloc[-lookback:].values
    indices = list(range(len(prices)))

    # Find local highs and lows using a 3-bar pivot
    local_highs = []
    local_lows = []

    for i in range(2, len(prices) - 2):
        if prices[i] >= prices[i - 1] and prices[i] >= prices[i - 2] and \
           prices[i] >= prices[i + 1] and prices[i] >= prices[i + 2]:
            local_highs.append((i, prices[i]))

        if prices[i] <= prices[i - 1] and prices[i] <= prices[i - 2] and \
           prices[i] <= prices[i + 1] and prices[i] <= prices[i + 2]:
            local_lows.append((i, prices[i]))

    if not local_highs or not local_lows:
        return []

    # Build pullbacks: pair each local high with the next local low
    pullbacks = []
    for hi_idx, hi_price in local_highs:
        # Find the next local low after this high
        for lo_idx, lo_price in local_lows:
            if lo_idx > hi_idx and hi_price > 0:
                depth_pct = (hi_price - lo_price) / hi_price * 100.0
                if depth_pct > 0:
                    pullbacks.append(Pullback(
                        start_idx=hi_idx,
                        end_idx=lo_idx,
                        high_price=hi_price,
                        low_price=lo_price,
                        depth_pct=depth_pct,
                    ))
                break  # Only pair with the nearest low

    return pullbacks


def detect_vcp(close: pd.Series, volume: pd.Series, lookback: int = 60) -> bool:
    """Identify Minervini's Volatility Contraction Pattern.

    Requires 3+ pullbacks where each is shallower than the prior,
    and declining volume through the pattern.

    Parameters
    ----------
    close   : pd.Series - daily close prices
    volume  : pd.Series - daily volume
    lookback: int - bars to look back for the pattern

    Returns
    -------
    bool : True if VCP detected
    """
    if len(close) < lookback or len(volume) < lookback:
        return False

    pullbacks = identify_pullbacks(close, lookback)

    if len(pullbacks) < 3:
        return False

    # Each pullback depth must be strictly less than the previous
    for i in range(1, len(pullbacks)):
        if pullbacks[i].depth_pct >= pullbacks[i - 1].depth_pct:
            return False

    # Volume should be declining: 10-day avg vol < 50-day avg vol
    vol_tail = volume.tail(max(50, lookback))
    if len(vol_tail) < 50:
        return False

    avg_10 = vol_tail.iloc[-10:].mean()
    avg_50 = vol_tail.iloc[-50:].mean()

    if avg_10 >= avg_50:
        return False

    logger.debug(
        "VCP detected: %d pullbacks, depths=%s, vol_ratio=%.2f",
        len(pullbacks),
        [f"{p.depth_pct:.1f}%" for p in pullbacks],
        avg_10 / avg_50 if avg_50 > 0 else 0,
    )
    return True
