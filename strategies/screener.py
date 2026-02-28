"""Stock screener — filters the Alpaca asset universe to a watchlist.

The screener applies lightweight filters (tradable, active, price range,
minimum volume) so that strategies only analyse liquid, actionable stocks.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from alpaca.data.timeframe import TimeFrame
from broker.client import AlpacaClient
from analysis.data_loader import load_bars

logger = logging.getLogger(__name__)


@dataclass
class ScreenerConfig:
    """Tuneable filters for the stock screener."""
    min_price: float = 5.0
    max_price: float = 1_000.0
    min_avg_volume: float = 500_000.0   # average daily volume
    lookback_bars: int = 50             # days of history for volume check
    max_candidates: int = 50            # cap the watchlist size


# ── Default watchlists ───────────────────────────────────────────────────
# You can also discover symbols dynamically via Alpaca's asset list,
# but starting from a curated set is faster and avoids rate-limit issues.

SP500_SAMPLE: List[str] = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK.B",
    "UNH", "JNJ", "V", "XOM", "JPM", "PG", "MA", "HD", "CVX", "MRK",
    "ABBV", "LLY", "PEP", "KO", "COST", "AVGO", "WMT", "MCD", "CSCO",
    "ACN", "CRM", "ABT", "TMO", "DHR", "NEE", "LIN", "ADBE", "NKE",
    "TXN", "ORCL", "PM", "RTX", "UPS", "QCOM", "LOW", "MS", "BA",
    "AMD", "INTC", "CAT", "GS", "AMGN",
]


class StockScreener:
    """Filter a universe of tickers down to tradable candidates."""

    def __init__(
        self,
        client: AlpacaClient,
        config: Optional[ScreenerConfig] = None,
        universe: Optional[List[str]] = None,
    ):
        self.client = client
        self.config = config or ScreenerConfig()
        self.universe = universe or SP500_SAMPLE

    def screen(self) -> List[str]:
        """Return a list of symbols that pass all filters.

        Steps
        -----
        1. Fetch recent daily bars for the entire universe (single API call).
        2. Drop symbols with insufficient data.
        3. Filter on latest close price range.
        4. Filter on average daily volume.
        5. Sort by volume descending and cap at max_candidates.
        """
        logger.info(
            "Screening %d symbols (price %.0f–%.0f, min vol %.0f) ...",
            len(self.universe),
            self.config.min_price,
            self.config.max_price,
            self.config.min_avg_volume,
        )

        frames = load_bars(
            self.client,
            symbols=self.universe,
            timeframe=TimeFrame.Day,
            limit=self.config.lookback_bars,
        )

        candidates: List[dict] = []
        min_bars = self.config.lookback_bars // 2
        for symbol, df in frames.items():
            if df.empty or len(df) < min_bars:
                logger.info(
                    "  %s: only %d bars (need %d) — skipped",
                    symbol, len(df), min_bars,
                )
                continue

            last_close = float(df["close"].iloc[-1])
            avg_vol = float(df["volume"].mean())

            if not (self.config.min_price <= last_close <= self.config.max_price):
                logger.info(
                    "  %s: price $%.2f outside range $%.0f–$%.0f — skipped",
                    symbol, last_close, self.config.min_price, self.config.max_price,
                )
                continue
            if avg_vol < self.config.min_avg_volume:
                logger.info(
                    "  %s: avg vol %.0fk < %.0fk min — skipped",
                    symbol, avg_vol / 1000, self.config.min_avg_volume / 1000,
                )
                continue

            logger.info(
                "  %s: PASSED (close=$%.2f, avg_vol=%.1fM)",
                symbol, last_close, avg_vol / 1_000_000,
            )
            candidates.append({
                "symbol": symbol,
                "last_close": last_close,
                "avg_volume": avg_vol,
            })

        # Sort most liquid first, then cap
        candidates.sort(key=lambda c: c["avg_volume"], reverse=True)
        candidates = candidates[: self.config.max_candidates]

        symbols = [c["symbol"] for c in candidates]
        logger.info("Screener passed %d / %d symbols", len(symbols), len(self.universe))
        return symbols
