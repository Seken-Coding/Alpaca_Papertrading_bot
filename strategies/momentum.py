"""Momentum / trend-following strategy.

Looks for stocks in established uptrends with accelerating momentum.

BUY when:
  - Price is above SMA-50 (uptrend)
  - SMA-20 is above SMA-50 (or just crossed above)
  - MACD histogram is positive (or just turned positive)
  - RSI is between 40-70 (momentum without being overbought)

SELL when the opposite conditions hold.
"""

import logging

import pandas as pd

from analysis import indicators as ind
from analysis.signals import Signal, TradeSignal, crossover, crossunder
from strategies.base import Strategy

logger = logging.getLogger(__name__)


class MomentumStrategy(Strategy):

    @property
    def name(self) -> str:
        return "Momentum"

    def indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = ind.sma(df, 20)
        df = ind.sma(df, 50)
        df = ind.ema(df, 9)
        df = ind.rsi(df)
        df = ind.macd(df)
        df = ind.atr(df)
        df = ind.adx(df)
        df = ind.relative_volume(df)
        return df

    def evaluate(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        if len(df) < 52:
            return TradeSignal(Signal.HOLD, symbol, 0.0, "Insufficient data")

        latest = df.iloc[-1]
        price = float(latest["close"])
        bullish: list[str] = []
        bearish: list[str] = []

        # ── Regime filter (ADX) ──────────────────────────────────────
        # Momentum works in trending markets (ADX > 22). Below that, trend
        # crossovers are unreliable noise — skip rather than fire false signals.
        adx_val = float(latest.get("adx", 0))
        trend_confirmed = adx_val > 15
        rvol_val = float(latest.get("rvol", 0))
        high_volume = rvol_val > 0.8

        # ── Trend direction ──────────────────────────────────────────
        above_sma50 = price > float(latest["sma_50"])
        sma20_above_50 = float(latest["sma_20"]) > float(latest["sma_50"])

        if above_sma50 and sma20_above_50:
            bullish.append("Price & SMA-20 above SMA-50 (uptrend)")
        elif not above_sma50 and not sma20_above_50:
            bearish.append("Price & SMA-20 below SMA-50 (downtrend)")

        # ── SMA crossover event (requires ADX + volume confirmation) ─
        if crossover(df["sma_20"], df["sma_50"]).iloc[-1]:
            if trend_confirmed and high_volume:
                bullish.append(
                    f"SMA-20/50 golden cross (ADX={adx_val:.0f} RVOL={rvol_val:.1f}x)"
                )
            else:
                # Low conviction: crossover without trend strength or volume
                pass
        elif crossunder(df["sma_20"], df["sma_50"]).iloc[-1]:
            if trend_confirmed and high_volume:
                bearish.append(
                    f"SMA-20/50 death cross (ADX={adx_val:.0f} RVOL={rvol_val:.1f}x)"
                )

        # ── MACD momentum ────────────────────────────────────────────
        hist = float(latest["macd_hist"])
        if hist > 0:
            bullish.append(f"MACD histogram positive ({hist:.3f})")
        elif hist < 0:
            bearish.append(f"MACD histogram negative ({hist:.3f})")

        if crossover(df["macd"], df["macd_signal"]).iloc[-1]:
            bullish.append("MACD bullish crossover")
        elif crossunder(df["macd"], df["macd_signal"]).iloc[-1]:
            bearish.append("MACD bearish crossover")

        # ── RSI confirmation ─────────────────────────────────────────
        rsi_val = float(latest["rsi"])
        if 40 <= rsi_val <= 70:
            bullish.append(f"RSI in momentum zone ({rsi_val:.1f})")
        elif rsi_val > 80:
            bearish.append(f"RSI extremely overbought ({rsi_val:.1f})")
        elif rsi_val < 30:
            bearish.append(f"RSI oversold ({rsi_val:.1f})")

        # ── Tally ────────────────────────────────────────────────────
        bull = len(bullish)
        bear = len(bearish)
        total = bull + bear or 1

        logger.info(
            "%s Momentum: bull=%d bear=%d | ADX=%.0f RVOL=%.1fx RSI=%.1f MACD_hist=%.3f",
            symbol, bull, bear, adx_val, rvol_val, rsi_val, hist,
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
        return TradeSignal(Signal.HOLD, symbol, price, "No clear momentum signal")
