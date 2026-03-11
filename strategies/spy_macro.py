"""SPY Macro Regime Overlay (Paul Tudor Jones / Nicolas Darvas).

Classifies the broad market regime using SPY as the benchmark.
This acts as a top-level filter: if SPY is in a bear market, the bot
reduces long exposure and tightens risk parameters.

Jones Rule: "Nothing good happens below the 200-day moving average."
Darvas Rule: "Only trade in bull markets."

Regime States:
  BULL    — SPY > 200-SMA AND 50-SMA > 200-SMA (both confirming uptrend)
  NEUTRAL — Mixed signals (one above, one below)
  BEAR    — SPY < 200-SMA AND 50-SMA < 200-SMA (confirmed downtrend)
"""

import logging
from dataclasses import dataclass

import pandas as pd

from analysis.cest_indicators import SMA

logger = logging.getLogger(__name__)

# Macro regime constants
MACRO_BULL = "BULL"
MACRO_NEUTRAL = "NEUTRAL"
MACRO_BEAR = "BEAR"

# Position size multiplier per macro regime
MACRO_SIZE_MULTIPLIER = {
    MACRO_BULL: 1.0,
    MACRO_NEUTRAL: 0.75,
    MACRO_BEAR: 0.50,
}

# SMA periods for macro detection
MACRO_SMA_LONG = 200
MACRO_SMA_SHORT = 50


@dataclass
class MacroRegime:
    """Current broad market regime assessment."""
    regime: str               # BULL, NEUTRAL, BEAR
    spy_price: float
    spy_sma200: float
    spy_sma50: float
    size_multiplier: float    # 1.0, 0.75, or 0.50
    long_allowed: bool        # False only in confirmed BEAR
    short_allowed: bool       # True in BEAR and NEUTRAL


def detect_spy_macro(spy_close: pd.Series) -> MacroRegime:
    """Classify the broad market regime using SPY price data.

    Parameters
    ----------
    spy_close : pd.Series - SPY daily close prices (need >= 200 bars)

    Returns
    -------
    MacroRegime with regime classification and trading constraints
    """
    if len(spy_close) < MACRO_SMA_LONG + 1:
        logger.warning(
            "Insufficient SPY data (%d bars, need %d). Defaulting to NEUTRAL.",
            len(spy_close), MACRO_SMA_LONG + 1,
        )
        return MacroRegime(
            regime=MACRO_NEUTRAL,
            spy_price=float(spy_close.iloc[-1]) if len(spy_close) > 0 else 0.0,
            spy_sma200=0.0,
            spy_sma50=0.0,
            size_multiplier=0.75,
            long_allowed=True,
            short_allowed=True,
        )

    price = float(spy_close.iloc[-1])
    sma200 = float(SMA(spy_close, MACRO_SMA_LONG).iloc[-1])
    sma50 = float(SMA(spy_close, MACRO_SMA_SHORT).iloc[-1])

    if pd.isna(sma200) or pd.isna(sma50):
        return MacroRegime(
            regime=MACRO_NEUTRAL,
            spy_price=price,
            spy_sma200=sma200 if not pd.isna(sma200) else 0.0,
            spy_sma50=sma50 if not pd.isna(sma50) else 0.0,
            size_multiplier=0.75,
            long_allowed=True,
            short_allowed=True,
        )

    price_above_200 = price > sma200
    sma50_above_200 = sma50 > sma200

    if price_above_200 and sma50_above_200:
        regime = MACRO_BULL
    elif not price_above_200 and not sma50_above_200:
        regime = MACRO_BEAR
    else:
        regime = MACRO_NEUTRAL

    size_mult = MACRO_SIZE_MULTIPLIER[regime]
    long_allowed = regime != MACRO_BEAR
    short_allowed = regime != MACRO_BULL

    logger.info(
        "SPY Macro: %s | Price=%.2f | SMA200=%.2f | SMA50=%.2f | "
        "Size mult=%.2f | Longs=%s | Shorts=%s",
        regime, price, sma200, sma50, size_mult,
        "YES" if long_allowed else "NO",
        "YES" if short_allowed else "NO",
    )

    return MacroRegime(
        regime=regime,
        spy_price=price,
        spy_sma200=sma200,
        spy_sma50=sma50,
        size_multiplier=size_mult,
        long_allowed=long_allowed,
        short_allowed=short_allowed,
    )
