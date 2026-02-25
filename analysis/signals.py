"""Signal generation from indicator-enriched DataFrames.

Provides low-level crossover/divergence helpers and a SignalGenerator
that strategies can configure and reuse.

Improvements over v1
--------------------
Weighted votes
  Not all signals are equally reliable.  SMA/MACD crossovers and RSI
  divergence carry higher conviction than a single RSI level or BB touch.
  Each condition now adds a floating-point weight to the bull/bear tally
  rather than an integer count, so the resulting ``strength`` value is a
  genuine conviction measure, not just a vote fraction.

Divergence detection
  ``detect_divergence()`` is exposed as a standalone helper for strategies
  that want to incorporate price/RSI divergence directly.

Regime-aware RSI thresholds
  The SignalGenerator accepts a ``rsi_oversold`` / ``rsi_overbought`` pair
  that can be tightened (e.g. 35/65) in ranging markets or loosened in
  trending ones without subclassing.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Signal types
# ─────────────────────────────────────────────────────────────────────────────

class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    """A discrete trade signal with metadata."""
    signal:   Signal
    symbol:   str
    price:    float
    reason:   str
    strength: float = 0.0   # 0.0 – 1.0, higher = stronger conviction


# ─────────────────────────────────────────────────────────────────────────────
# Crossover helpers
# ─────────────────────────────────────────────────────────────────────────────

def crossover(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Return boolean Series that is True where *a* crosses above *b*."""
    return (series_a > series_b) & (series_a.shift(1) <= series_b.shift(1))


def crossunder(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Return boolean Series that is True where *a* crosses below *b*."""
    return (series_a < series_b) & (series_a.shift(1) >= series_b.shift(1))


# ─────────────────────────────────────────────────────────────────────────────
# Divergence helper
# ─────────────────────────────────────────────────────────────────────────────

def detect_divergence(df: pd.DataFrame, period: int = 20) -> int:
    """Check the most recent bar for RSI divergence.

    Returns
    -------
    +1  Bullish divergence (price near N-bar low, RSI recovering)
    -1  Bearish divergence (price near N-bar high, RSI lagging)
     0  No divergence detected, or insufficient data / missing columns
    """
    if "rsi_divergence" in df.columns:
        val = df["rsi_divergence"].iloc[-1]
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    # Fallback: compute on the fly if the column is absent
    if "rsi" not in df.columns or len(df) < period + 2:
        return 0

    close = df["close"]
    rsi   = df["rsi"]

    p_max = close.rolling(period).max().iloc[-1]
    p_min = close.rolling(period).min().iloc[-1]
    r_max = rsi.rolling(period).max().iloc[-1]
    r_min = rsi.rolling(period).min().iloc[-1]
    c     = close.iloc[-1]
    r     = rsi.iloc[-1]

    if c >= p_max * 0.98 and r <= r_max - 8:
        return -1   # Bearish
    if c <= p_min * 1.02 and r >= r_min + 8:
        return +1   # Bullish
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Signal weights
# ─────────────────────────────────────────────────────────────────────────────

# Weights reflect approximate historical reliability of each condition class.
# Higher weight = the condition is a stronger stand-alone signal.
_W_DIVERGENCE  = 4.0   # RSI divergence — highest conviction
_W_MA_CROSS    = 3.0   # Golden / death cross
_W_MACD_CROSS  = 3.0   # MACD signal-line crossover
_W_RSI_EXTREME = 2.0   # RSI at overbought / oversold level
_W_BB_EXTREME  = 1.5   # Price at Bollinger Band
_W_MACD_HIST   = 1.0   # MACD histogram direction (supporting signal)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SignalConfig:
    """Tuneable thresholds for signal generation."""
    rsi_oversold:    float = 30.0
    rsi_overbought:  float = 70.0
    sma_fast:        int   = 20
    sma_slow:        int   = 50
    macd_enabled:    bool  = True
    bb_enabled:      bool  = True
    divergence_enabled: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Signal generator
# ─────────────────────────────────────────────────────────────────────────────

class SignalGenerator:
    """Evaluate the latest bar of an indicator DataFrame and emit a TradeSignal.

    Each condition adds a weighted contribution to a bull or bear tally.
    The resulting ``strength`` is ``winning_weight / total_weight`` — a
    genuine conviction measure rather than a simple vote fraction.
    """

    def __init__(self, config: Optional[SignalConfig] = None):
        self.config = config or SignalConfig()

    def evaluate(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """Analyse *df* (must already have indicator columns) and return
        a TradeSignal for the most recent bar."""
        if len(df) < 2:
            return TradeSignal(Signal.HOLD, symbol, 0.0, "Insufficient data")

        latest  = df.iloc[-1]
        price   = float(latest["close"])
        cfg     = self.config

        bull_w: float = 0.0
        bear_w: float = 0.0
        bullish: list[str] = []
        bearish: list[str] = []

        # ── RSI divergence (highest weight) ──────────────────────────────
        if cfg.divergence_enabled:
            div = detect_divergence(df)
            if div > 0:
                bull_w += _W_DIVERGENCE
                bullish.append("Bullish RSI divergence")
            elif div < 0:
                bear_w += _W_DIVERGENCE
                bearish.append("Bearish RSI divergence")

        # ── SMA crossover ─────────────────────────────────────────────────
        fast_col = f"sma_{cfg.sma_fast}"
        slow_col = f"sma_{cfg.sma_slow}"
        if fast_col in df.columns and slow_col in df.columns:
            if crossover(df[fast_col], df[slow_col]).iloc[-1]:
                bull_w += _W_MA_CROSS
                bullish.append(f"SMA golden cross ({cfg.sma_fast}/{cfg.sma_slow})")
            elif crossunder(df[fast_col], df[slow_col]).iloc[-1]:
                bear_w += _W_MA_CROSS
                bearish.append(f"SMA death cross ({cfg.sma_fast}/{cfg.sma_slow})")

        # ── RSI level ─────────────────────────────────────────────────────
        if "rsi" in df.columns:
            rsi_val = float(latest["rsi"])
            if rsi_val <= cfg.rsi_oversold:
                bull_w += _W_RSI_EXTREME
                bullish.append(f"RSI oversold ({rsi_val:.1f})")
            elif rsi_val >= cfg.rsi_overbought:
                bear_w += _W_RSI_EXTREME
                bearish.append(f"RSI overbought ({rsi_val:.1f})")

        # ── MACD crossover + histogram direction ──────────────────────────
        if cfg.macd_enabled and "macd" in df.columns and "macd_signal" in df.columns:
            if crossover(df["macd"], df["macd_signal"]).iloc[-1]:
                bull_w += _W_MACD_CROSS
                bullish.append("MACD bullish crossover")
            elif crossunder(df["macd"], df["macd_signal"]).iloc[-1]:
                bear_w += _W_MACD_CROSS
                bearish.append("MACD bearish crossover")

            # Histogram direction (supporting, lower weight)
            if "macd_hist" in df.columns and len(df) >= 2:
                hist_now  = float(latest["macd_hist"])
                hist_prev = float(df["macd_hist"].iloc[-2])
                if hist_now > 0 and hist_now > hist_prev:
                    bull_w += _W_MACD_HIST
                    bullish.append("MACD histogram rising")
                elif hist_now < 0 and hist_now < hist_prev:
                    bear_w += _W_MACD_HIST
                    bearish.append("MACD histogram falling")

        # ── Bollinger Bands ───────────────────────────────────────────────
        if cfg.bb_enabled and "bb_lower" in df.columns and "bb_upper" in df.columns:
            if price <= float(latest["bb_lower"]):
                bull_w += _W_BB_EXTREME
                bullish.append("Price at lower Bollinger Band")
            elif price >= float(latest["bb_upper"]):
                bear_w += _W_BB_EXTREME
                bearish.append("Price at upper Bollinger Band")

        # ── Tally ─────────────────────────────────────────────────────────
        total_w = bull_w + bear_w
        if total_w == 0:
            return TradeSignal(Signal.HOLD, symbol, price, "No clear signal")

        if bull_w > bear_w:
            strength = bull_w / total_w
            return TradeSignal(
                Signal.BUY, symbol, price,
                reason="; ".join(bullish),
                strength=round(strength, 3),
            )
        if bear_w > bull_w:
            strength = bear_w / total_w
            return TradeSignal(
                Signal.SELL, symbol, price,
                reason="; ".join(bearish),
                strength=round(strength, 3),
            )
        return TradeSignal(Signal.HOLD, symbol, price, "Signals balanced — no edge")
