"""Strategy scanner — orchestrates the full pipeline.

    Screener  →  Data loading  →  Indicators  →  Strategy evaluation  →  Ranked recommendations

Usage:
    scanner = StrategyScanner(client, strategies=[MomentumStrategy(), MeanReversionStrategy()])
    recs = scanner.scan()
    for r in recs:
        print(r)
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from alpaca.data.timeframe import TimeFrame

from broker.client import AlpacaClient
from analysis.data_loader import load_bars
from analysis.indicators import apply_all
from analysis.signals import Signal, TradeSignal
from strategies.base import Strategy
from strategies.screener import StockScreener, ScreenerConfig

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    """A ranked trade recommendation produced by the scanner."""
    symbol: str
    price: float
    signal: Signal
    strategy: str
    strength: float
    reason: str
    atr: float = 0.0  # Latest ATR — used by ExecutionEngine for position sizing

    def __str__(self) -> str:
        arrow = {"BUY": "▲", "SELL": "▼", "HOLD": "—"}.get(self.signal.value, "?")
        return (
            f"{arrow} {self.signal.value:<4}  {self.symbol:<6}  "
            f"${self.price:>9.2f}  "
            f"strength={self.strength:.0%}  "
            f"[{self.strategy}]  {self.reason}"
        )


class StrategyScanner:
    """Run one or more strategies across screened stocks and rank the results."""

    def __init__(
        self,
        client: AlpacaClient,
        strategies: List[Strategy],
        screener_config: Optional[ScreenerConfig] = None,
        universe: Optional[List[str]] = None,
        lookback_bars: int = 500,
    ):
        self.client = client
        self.strategies = strategies
        self.screener = StockScreener(client, screener_config, universe)
        self.lookback_bars = lookback_bars

    def scan(self) -> List[Recommendation]:
        """Execute the full scan pipeline and return sorted recommendations.

        Returns only BUY and SELL signals (HOLD is filtered out).
        Results are sorted by strength descending.
        """
        # 1 — Screen
        symbols = self.screener.screen()
        if not symbols:
            logger.warning("Screener returned zero candidates")
            return []

        # 2 — Load data (one bulk call for all candidates)
        logger.info("Loading %d-bar history for %d candidates ...", self.lookback_bars, len(symbols))
        frames = load_bars(
            self.client,
            symbols=symbols,
            timeframe=TimeFrame.Day,
            limit=self.lookback_bars,
        )

        # 3 — Compute all indicators once per symbol, then evaluate each strategy
        recommendations: List[Recommendation] = []
        for symbol, df in frames.items():
            if df.empty:
                continue

            # Pre-compute the full 55-column indicator suite once.
            # Both strategies only use columns that apply_all() already provides,
            # so we skip strategy.indicators() and pass the enriched df directly.
            try:
                enriched = apply_all(df)
            except Exception:
                logger.exception("Indicator computation failed for %s — skipping", symbol)
                continue

            # Capture key indicator values for logging
            latest = enriched.iloc[-1]
            atr_val = 0.0
            if "atr" in enriched.columns:
                raw = latest["atr"]
                atr_val = float(raw) if raw == raw else 0.0  # NaN guard

            def _safe(col: str) -> float:
                v = latest.get(col, float("nan"))
                return float(v) if v == v else 0.0

            logger.info(
                "  %s indicators: RSI=%.1f ADX=%.1f RVOL=%.1fx ATR=$%.2f MACD_hist=%.3f close=$%.2f",
                symbol, _safe("rsi"), _safe("adx"), _safe("rvol"),
                atr_val, _safe("macd_hist"), _safe("close"),
            )

            for strategy in self.strategies:
                try:
                    signal: TradeSignal = strategy.evaluate(enriched.copy(), symbol)
                except Exception:
                    logger.exception("Error running %s on %s", strategy.name, symbol)
                    continue

                if signal.signal == Signal.HOLD:
                    logger.info(
                        "  %s [%s]: HOLD — %s", symbol, strategy.name, signal.reason
                    )
                    continue

                logger.info(
                    "  %s [%s]: %s strength=%.0f%% — %s",
                    symbol, strategy.name, signal.signal.value,
                    signal.strength * 100, signal.reason,
                )

                recommendations.append(Recommendation(
                    symbol=signal.symbol,
                    price=signal.price,
                    signal=signal.signal,
                    strategy=strategy.name,
                    strength=signal.strength,
                    reason=signal.reason,
                    atr=atr_val,
                ))

        # 4 — De-duplicate: keep the highest-strength signal per symbol.
        # Multiple strategies can signal the same symbol; only the best proceeds.
        best: dict[str, Recommendation] = {}
        for rec in recommendations:
            if rec.symbol not in best or rec.strength > best[rec.symbol].strength:
                best[rec.symbol] = rec
        recommendations = list(best.values())

        # 5 — Rank by strength (highest first)
        recommendations.sort(key=lambda r: r.strength, reverse=True)

        logger.info(
            "Scan complete — %d actionable recommendations (%d BUY, %d SELL)",
            len(recommendations),
            sum(1 for r in recommendations if r.signal == Signal.BUY),
            sum(1 for r in recommendations if r.signal == Signal.SELL),
        )
        return recommendations
