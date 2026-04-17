"""Shared file-based cache for bar (OHLCV) data.

Repeated scanner runs often request the same market data from Alpaca.
This module stores fetched bar DataFrames on disk so the first request
hits the API and subsequent requests within the TTL read from the local
cache.

Cache files live under ``cache/bars/`` (configurable) and are organised as::

    cache/bars/{symbol}_{timeframe}_{limit}.pkl

Cross-process safety is achieved by writing to a temporary file and
atomically renaming it into place.
"""

import hashlib
import logging
import os
import pickle
import tempfile
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Default cache directory (relative to project root)
_DEFAULT_CACHE_DIR = Path("cache/bars")

# Default TTL in seconds (15 minutes — covers the typical startup window)
_DEFAULT_TTL = int(os.getenv("BAR_CACHE_TTL", "900"))


class BarCache:
    """Disk-backed DataFrame cache with configurable TTL."""

    def __init__(self, cache_dir: Path | str | None = None, ttl: int | None = None):
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._ttl = ttl if ttl is not None else _DEFAULT_TTL
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
        """Return cached DataFrame if fresh, else None."""
        path = self._key_path(symbol, timeframe, limit)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self._ttl:
            logger.debug("Cache expired for %s (age=%.0fs, ttl=%ds)", symbol, age, self._ttl)
            return None
        try:
            with open(path, "rb") as f:
                df = pickle.load(f)
            logger.debug("Cache hit for %s (%d bars, age=%.0fs)", symbol, len(df), age)
            return df
        except Exception:
            logger.debug("Cache read failed for %s — will re-fetch", symbol)
            return None

    def put(self, symbol: str, timeframe: str, limit: int, df: pd.DataFrame) -> None:
        """Write a DataFrame to the cache (atomic via rename)."""
        if df.empty:
            return
        path = self._key_path(symbol, timeframe, limit)
        try:
            fd, tmp = tempfile.mkstemp(dir=self._cache_dir, suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except Exception:
            logger.debug("Cache write failed for %s", symbol, exc_info=True)

    def get_many(self, symbols: list[str], timeframe: str, limit: int) -> dict[str, pd.DataFrame]:
        """Return {symbol: DataFrame} for all cached symbols; omit misses."""
        result = {}
        for sym in symbols:
            df = self.get(sym, timeframe, limit)
            if df is not None:
                result[sym] = df
        return result

    def put_many(self, data: dict[str, pd.DataFrame], timeframe: str, limit: int) -> None:
        """Cache multiple DataFrames at once."""
        for sym, df in data.items():
            self.put(sym, timeframe, limit, df)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _key_path(self, symbol: str, timeframe: str, limit: int) -> Path:
        """Deterministic cache file path for a given request."""
        return self._cache_dir / f"{symbol}_{timeframe}_{limit}.pkl"


# Module-level singleton so all callers in the same process share one instance.
# Separate processes share cached files via the filesystem.
_shared_cache: BarCache | None = None


def get_shared_cache() -> BarCache:
    """Return the process-wide BarCache singleton."""
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = BarCache()
    return _shared_cache
