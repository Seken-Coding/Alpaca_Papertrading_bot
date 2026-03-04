"""Stock screener — filters the Alpaca asset universe to a watchlist.

The screener applies lightweight filters (tradable, active, price range,
minimum volume) so that strategies only analyse liquid, actionable stocks.

Supports two modes:
  - static  (default): uses the hardcoded SP500_SAMPLE list
  - dynamic: discovers all tradable US stocks via Alpaca's get_assets() API
"""

import logging
import time as _time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from alpaca.data.timeframe import TimeFrame
from alpaca.trading.enums import AssetExchange
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
    max_candidates: int = 100           # cap the watchlist size
    batch_size: int = 50                # symbols per load_bars() call


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

# Regulated US equity exchanges (excludes OTC, crypto, FTX, etc.)
_ALLOWED_EXCHANGES: frozenset = frozenset({
    AssetExchange.NYSE,
    AssetExchange.NASDAQ,
    AssetExchange.ARCA,
    AssetExchange.NYSEARCA,
    AssetExchange.AMEX,
    AssetExchange.BATS,
    AssetExchange.ASCX,
})

# Module-level cache: (symbols_list, monotonic_timestamp)
_asset_cache: tuple[list[str], float] | None = None


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

    def screen(
        self,
        universe_mode: str = "static",
        cache_ttl: int = 86400,
    ) -> List[str]:
        """Return a list of symbols that pass all filters.

        Parameters
        ----------
        universe_mode : str
            "static" uses self.universe (SP500_SAMPLE by default).
            "dynamic" discovers tradable US stocks via get_assets().
        cache_ttl : int
            Seconds to reuse the cached asset list (dynamic mode only).
        """
        if universe_mode == "dynamic":
            symbols_to_screen = self._discover_universe(cache_ttl)
        else:
            symbols_to_screen = self.universe

        logger.info(
            "Screening %d symbols (price %.0f–%.0f, min vol %.0f) ...",
            len(symbols_to_screen),
            self.config.min_price,
            self.config.max_price,
            self.config.min_avg_volume,
        )

        # Batch load_bars() to avoid sending hundreds of symbols in one call
        frames: Dict[str, pd.DataFrame] = {}
        batch_size = self.config.batch_size
        batches = [
            symbols_to_screen[i : i + batch_size]
            for i in range(0, len(symbols_to_screen), batch_size)
        ]
        logger.info(
            "Loading bars in %d batch(es) of up to %d symbols ...",
            len(batches), batch_size,
        )
        for idx, batch in enumerate(batches, 1):
            try:
                batch_frames = load_bars(
                    self.client,
                    symbols=batch,
                    timeframe=TimeFrame.Day,
                    limit=self.config.lookback_bars,
                )
                frames.update(batch_frames)
            except Exception as exc:
                logger.warning(
                    "Batch %d/%d failed (%d symbols): %s — skipping batch",
                    idx, len(batches), len(batch), exc,
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
        logger.info(
            "Screener passed %d / %d symbols",
            len(symbols), len(symbols_to_screen),
        )
        return symbols

    def _discover_universe(self, cache_ttl: int) -> list[str]:
        """Fetch tradable US equity symbols from Alpaca, with module-level caching."""
        global _asset_cache

        now = _time.monotonic()
        if _asset_cache is not None:
            symbols, fetched_at = _asset_cache
            age = now - fetched_at
            if age < cache_ttl:
                logger.info(
                    "Asset cache hit — %d symbols (age %.0fs / ttl %ds)",
                    len(symbols), age, cache_ttl,
                )
                return symbols

        logger.info("Asset cache miss — fetching asset list from Alpaca ...")
        try:
            assets = self.client.get_assets()
        except Exception as exc:
            logger.error(
                "get_assets() failed: %s — falling back to SP500_SAMPLE (%d symbols)",
                exc, len(SP500_SAMPLE),
            )
            return list(SP500_SAMPLE)

        total = len(assets)
        filtered = [
            a.symbol
            for a in assets
            if a.tradable and a.exchange in _ALLOWED_EXCHANGES
        ]

        logger.info(
            "Asset discovery: %d total → %d after tradable+exchange filter",
            total, len(filtered),
        )

        _asset_cache = (filtered, now)
        return filtered
