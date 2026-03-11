"""Darvas Box Breakout Detection (Nicolas Darvas).

Identifies price consolidation "boxes" — defined by a ceiling (highest high
over N bars where price fails to break above) and a floor (lowest low within
that box period). A breakout occurs when price closes above the box ceiling
on above-average volume.

Used as an additional confluence signal in trend-following entries.
"""

import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class DarvasBox:
    """Represents a completed Darvas Box."""
    ceiling: float       # box top (highest high)
    floor: float         # box bottom (lowest low within ceiling period)
    ceiling_bar: int     # index where ceiling was established
    floor_bar: int       # index where floor was established
    width_bars: int      # number of bars in the box


def identify_darvas_boxes(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 60,
    confirmation_bars: int = 3,
) -> list[DarvasBox]:
    """Identify Darvas Boxes within the lookback window.

    A box is formed when:
    1. Price makes a new high (potential ceiling)
    2. Price fails to break above that high for `confirmation_bars` consecutive bars
    3. Ceiling is confirmed → find the lowest low since the ceiling bar (floor)
    4. Floor is confirmed when price holds above it for `confirmation_bars` bars

    Parameters
    ----------
    high   : pd.Series - daily high prices
    low    : pd.Series - daily low prices
    close  : pd.Series - daily close prices
    lookback : int - bars to look back
    confirmation_bars : int - bars needed to confirm ceiling/floor

    Returns
    -------
    list[DarvasBox] : completed boxes, most recent last
    """
    if len(high) < lookback:
        return []

    h = high.iloc[-lookback:].values
    lo = low.iloc[-lookback:].values
    c = close.iloc[-lookback:].values
    n = len(h)

    boxes = []
    i = confirmation_bars

    while i < n - confirmation_bars:
        # Step 1: Find potential ceiling — a bar whose high is not exceeded
        # for the next `confirmation_bars` bars
        potential_ceiling = h[i]
        ceiling_confirmed = True

        for j in range(1, confirmation_bars + 1):
            if i + j >= n:
                ceiling_confirmed = False
                break
            if h[i + j] > potential_ceiling:
                ceiling_confirmed = False
                break

        if not ceiling_confirmed:
            i += 1
            continue

        ceiling_bar = i
        ceiling_val = potential_ceiling

        # Step 2: Find floor — lowest low after ceiling confirmation
        floor_start = ceiling_bar + confirmation_bars
        if floor_start >= n - confirmation_bars:
            break

        # Scan forward for the floor
        floor_val = lo[floor_start]
        floor_bar = floor_start

        for k in range(floor_start + 1, min(floor_start + 20, n)):
            if h[k] > ceiling_val:
                # Breakout — box ends here
                break
            if lo[k] < floor_val:
                floor_val = lo[k]
                floor_bar = k

        # Floor must be confirmed (price holds above it)
        floor_confirmed = True
        for j in range(1, min(confirmation_bars + 1, n - floor_bar)):
            if floor_bar + j >= n:
                floor_confirmed = False
                break
            if lo[floor_bar + j] < floor_val:
                floor_confirmed = False
                break

        if floor_confirmed and ceiling_val > floor_val:
            boxes.append(DarvasBox(
                ceiling=ceiling_val,
                floor=floor_val,
                ceiling_bar=ceiling_bar,
                floor_bar=floor_bar,
                width_bars=floor_bar - ceiling_bar + confirmation_bars,
            ))

        # Move past this box
        i = floor_bar + confirmation_bars

    return boxes


def detect_darvas_breakout(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    lookback: int = 60,
    volume_sma_period: int = 20,
) -> bool:
    """Detect if current price is breaking out of a Darvas Box.

    Breakout conditions:
    1. At least one completed Darvas Box exists
    2. Current close > most recent box ceiling
    3. Current volume > 1.5× volume SMA(20)

    Parameters
    ----------
    high   : pd.Series - daily high prices
    low    : pd.Series - daily low prices
    close  : pd.Series - daily close prices
    volume : pd.Series - daily volume
    lookback : int - bars to scan for boxes
    volume_sma_period : int - period for volume average

    Returns
    -------
    bool : True if Darvas breakout detected
    """
    if len(close) < lookback or len(volume) < volume_sma_period:
        return False

    boxes = identify_darvas_boxes(high, low, close, lookback)
    if not boxes:
        return False

    current_close = close.iloc[-1]
    current_volume = volume.iloc[-1]
    avg_volume = volume.rolling(window=volume_sma_period).mean().iloc[-1]

    # Use the most recent box
    latest_box = boxes[-1]

    # Breakout: close above ceiling with volume confirmation
    price_breakout = current_close > latest_box.ceiling
    volume_confirm = current_volume > avg_volume * 1.5

    if price_breakout and volume_confirm:
        logger.debug(
            "Darvas breakout: close=%.2f > ceiling=%.2f | floor=%.2f | "
            "vol_ratio=%.2f | box_width=%d bars",
            current_close, latest_box.ceiling, latest_box.floor,
            current_volume / avg_volume if avg_volume > 0 else 0,
            latest_box.width_bars,
        )
        return True

    return False
