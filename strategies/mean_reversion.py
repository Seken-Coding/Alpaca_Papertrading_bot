"""Mean-reversion strategy.

Identifies stocks that have deviated significantly from their mean
and are likely to revert.

BUY when:
  - RSI is oversold (< 30)
  - Price is at or below the lower Bollinger Band
  - MACD histogram is starting to turn upward (momentum shift)

SELL when:
  - RSI is overbought (> 70)
  - Price is at or above the upper Bollinger Band
  - MACD histogram is turning downward
"""

import logging

import pandas as pd

from analysis import indicators as ind
from analysis.signals import Signal, TradeSignal, crossover, crossunder
from strategies.base import Strategy

logger = logging.getLogger(__name__)


class MeanReversionStrategy(Strategy):

    @property
    def name(self) -> str:
        return "MeanReversion"

    def indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = ind.rsi(df)
        df = ind.bollinger_bands(df, period=20, num_std=2.0)
        df = ind.macd(df)
        df = ind.sma(df, 20)
        df = ind.atr(df)
        df = ind.adx(df)
        return df

    def evaluate(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        if len(df) < 26:
            return TradeSignal(Signal.HOLD, symbol, 0.0, "Insufficient data")

        latest = df.iloc[-1]
        price = float(latest["close"])

        # ── Regime filter (ADX) ──────────────────────────────────────
        # Mean reversion is dangerous in strong trends (ADX > 25) — catching
        # a falling knife or shorting a breakout.  Skip entirely if trending.
        adx_val = float(latest.get("adx", 0))
        if adx_val > 25:
            logger.info(
                "%s MeanReversion: ADX=%.0f > 25 — trending, skipped",
                symbol, adx_val,
            )
            return TradeSignal(
                Signal.HOLD, symbol, price,
                f"Trending market (ADX={adx_val:.0f} > 25) — mean reversion skipped",
            )

        bullish: list[str] = []
        bearish: list[str] = []

        rsi_val = float(latest["rsi"])
        bb_lower = float(latest["bb_lower"])
        bb_upper = float(latest["bb_upper"])
        bb_middle = float(latest["bb_middle"])
        macd_hist = float(latest["macd_hist"])

        # ── Oversold bounce (BUY) ────────────────────────────────────
        if rsi_val < 30:
            bullish.append(f"RSI oversold ({rsi_val:.1f})")
        if price <= bb_lower:
            bullish.append("Price at/below lower Bollinger Band")

        # Check if MACD histogram is turning up (momentum shift)
        if len(df) >= 3:
            hist_prev = float(df["macd_hist"].iloc[-2])
            if macd_hist > hist_prev and hist_prev < 0:
                bullish.append("MACD histogram turning up from negative")

        # Price far below the 20-SMA (stretched)
        sma20 = float(latest["sma_20"])
        deviation = (price - sma20) / sma20 if sma20 else 0
        if deviation < -0.03:
            bullish.append(f"Price {deviation:.1%} below SMA-20")

        # ── Overbought reversal (SELL) ───────────────────────────────
        if rsi_val > 70:
            bearish.append(f"RSI overbought ({rsi_val:.1f})")
        if price >= bb_upper:
            bearish.append("Price at/above upper Bollinger Band")

        if len(df) >= 3:
            hist_prev = float(df["macd_hist"].iloc[-2])
            if macd_hist < hist_prev and hist_prev > 0:
                bearish.append("MACD histogram turning down from positive")

        if deviation > 0.03:
            bearish.append(f"Price {deviation:.1%} above SMA-20")

        # ── Tally ────────────────────────────────────────────────────
        bull = len(bullish)
        bear = len(bearish)
        total = bull + bear or 1

        logger.info(
            "%s MeanReversion: bull=%d bear=%d | ADX=%.0f RSI=%.1f BB_pos=%.2f MACD_hist=%.3f",
            symbol, bull, bear, adx_val, rsi_val,
            (price - bb_middle) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0,
            macd_hist,
        )

        if bull > bear:
            return TradeSignal(
                Signal.BUY, symbol, price,
                reason="; ".join(bullish),
                strength=bull / total,
            )
        if bear > bull:
            return TradeSignal(
                Signal.SELL, symbol, price,
                reason="; ".join(bearish),
                strength=bear / total,
            )
        return TradeSignal(Signal.HOLD, symbol, price, "No mean-reversion signal")
