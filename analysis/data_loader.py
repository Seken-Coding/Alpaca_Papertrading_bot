"""Fetch market data from Alpaca and normalise into pandas DataFrames."""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from alpaca.data.timeframe import TimeFrame
from broker.client import AlpacaClient

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}
_MIN_BARS = 10  # Fewer than this is useless for any strategy


def _validate_bars(symbol: str, df: pd.DataFrame) -> bool:
    """Return True if *df* passes basic sanity checks; log and return False otherwise."""
    if df.empty:
        logger.warning("  %s: 0 bars returned — skipping", symbol)
        return False
    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        logger.warning("  %s: missing columns %s — skipping", symbol, missing)
        return False
    if len(df) < _MIN_BARS:
        logger.warning(
            "  %s: only %d bars (minimum %d) — skipping", symbol, len(df), _MIN_BARS
        )
        return False
    # OHLC invariant: high must be >= low on every bar
    bad_rows = int((df["high"] < df["low"]).sum())
    if bad_rows > 0:
        logger.warning(
            "  %s: %d bar(s) with high < low (data corruption?) — skipping",
            symbol, bad_rows,
        )
        return False
    return True


def bars_to_dataframe(bars) -> Dict[str, pd.DataFrame]:
    """Convert an Alpaca BarSet response into {symbol: DataFrame}.

    Each DataFrame has columns: open, high, low, close, volume, vwap,
    trade_count and a DatetimeIndex named 'timestamp'.
    """
    frames: Dict[str, pd.DataFrame] = {}
    for symbol, bar_list in bars.data.items():
        rows = [
            {
                "timestamp": b.timestamp,
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
                "vwap": float(b.vwap),
                "trade_count": int(b.trade_count),
            }
            for b in bar_list
        ]
        df = pd.DataFrame(rows)
        if not df.empty:
            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)
        frames[symbol] = df
    return frames


def load_bars(
    client: AlpacaClient,
    symbols: List[str],
    timeframe: TimeFrame,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> Dict[str, pd.DataFrame]:
    """High-level helper: fetch bars and return {symbol: DataFrame}.

    Parameters
    ----------
    client : AlpacaClient
        Initialised broker client.
    symbols : list[str]
        Ticker symbols to fetch, e.g. ["AAPL", "MSFT"].
    timeframe : TimeFrame
        Bar resolution, e.g. TimeFrame.Day, TimeFrame.Hour.
    start / end : datetime, optional
        Date range boundaries.
    limit : int, optional
        Maximum number of bars per symbol.

    Returns
    -------
    dict[str, DataFrame]
        OHLCV DataFrames keyed by symbol.
    """
    logger.info(
        "Loading bars for %s | timeframe=%s | start=%s | end=%s | limit=%s",
        symbols, timeframe, start, end, limit,
    )
    raw = client.get_bars(
        symbols=symbols,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
    )
    frames = bars_to_dataframe(raw)
    validated: Dict[str, pd.DataFrame] = {}
    for sym, df in frames.items():
        logger.info("  %s: %d bars loaded", sym, len(df))
        if _validate_bars(sym, df):
            validated[sym] = df
    return validated


def load_bars_single(
    client: AlpacaClient,
    symbol: str,
    timeframe: TimeFrame,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Convenience wrapper for a single symbol — returns a DataFrame directly."""
    frames = load_bars(client, [symbol], timeframe, start, end, limit)
    return frames.get(symbol, pd.DataFrame())
