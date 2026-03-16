"""CEST Universe Scanning.

Manages the trading universe:
  - Core ETFs (always scanned)
  - Dynamic top-50 stocks by 6-month relative strength from S&P 500
  - Weekly refresh (Sunday night or pre-market Monday)
"""

import logging

import pandas as pd

from config import cest_settings as cfg
from analysis.cest_indicators import ATR

logger = logging.getLogger(__name__)

# S&P 500 representative symbols for universe scanning
# In production, this would be fetched from a data provider
SP500_SYMBOLS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK.B",
    "UNH", "LLY", "JPM", "V", "XOM", "AVGO", "JNJ", "MA", "PG", "HD",
    "COST", "MRK", "ABBV", "CVX", "ADBE", "CRM", "KO", "WMT", "PEP",
    "ACN", "TMO", "MCD", "CSCO", "LIN", "ABT", "NFLX", "AMD", "ORCL",
    "DHR", "TXN", "PM", "INTC", "CMCSA", "WFC", "BA", "NEE", "UPS",
    "RTX", "BMY", "QCOM", "AMGN", "SBUX", "LOW", "HON", "GS", "CAT",
    "INTU", "ISRG", "BLK", "AXP", "DE", "ELV", "ADI", "GILD", "PLD",
    "SYK", "MDLZ", "BKNG", "REGN", "ADP", "LRCX", "VRTX", "MMC",
    "PANW", "CI", "MO", "SCHW", "CB", "SO", "DUK", "KLAC", "SNPS",
    "BSX", "PGR", "CME", "ZTS", "ICE", "FI", "CL", "ITW", "SHW",
    "CDNS", "EQIX", "EOG", "MPC", "APD", "HCA", "PYPL", "PSA", "MCK",
    "NOC", "USB", "GD", "ORLY", "MSI", "CTAS", "EMR", "NSC", "RSG",
    "MAR", "ABNB", "DXCM", "CCI", "SLB", "WM", "AJG", "WELL", "GM",
    "F", "FDX", "TGT", "COF", "BK", "FTNT", "SRE", "AFL", "DLR",
    "OKE", "MET", "TRV", "AZO", "PSX", "SPG", "ALL", "KMB", "D",
    "AEP", "O", "GIS", "ROST", "PAYX", "HLT", "EW", "A", "YUM",
    "NEM", "KHC", "FAST", "PPG", "IDXX", "CARR", "ODFL", "BKR",
    "CTSH", "VRSK", "HPQ", "MCHP", "ON", "KDP", "GEHC", "CPRT",
    "CBRE", "EXC", "MNST", "FANG", "KVUE", "HSY", "BIIB", "ANSS",
    "HES", "IT", "ROK", "XEL", "IFF", "AWK", "STZ", "ED", "EIX",
    "EA", "DLTR", "VICI", "MLM", "APTV", "VMC", "TRGP", "DAL",
    "DVN", "ACGL", "NUE", "HIG", "GPC", "RMD", "WAT", "MTB",
    "CDW", "RJF", "WEC", "DOV", "TSCO", "FTV", "DTE", "WBD",
]


_BATCH_SIZE = 50  # symbols per batch API call


def _evaluate_symbol(symbol, bars):
    """Evaluate a single symbol's bars against universe filters.

    Returns a candidate dict or None if the symbol doesn't pass filters.
    """
    if bars.empty or len(bars) < 126:
        return None

    close = bars["close"]
    high = bars["high"]
    low = bars["low"]
    volume = bars["volume"]
    price = close.iloc[-1]

    if price < cfg.MIN_PRICE:
        return None

    avg_dollar_vol = (close.tail(20) * volume.tail(20)).mean()
    if avg_dollar_vol < cfg.MIN_DOLLAR_VOLUME:
        return None

    atr_series = ATR(high, low, close, period=cfg.ATR_PERIOD)
    atr_val = atr_series.iloc[-1]
    if pd.isna(atr_val) or price <= 0:
        return None
    atr_pct = atr_val / price * 100.0
    if atr_pct < cfg.ATR_PCT_MIN or atr_pct > cfg.ATR_PCT_MAX:
        return None

    price_6m_ago = close.iloc[-126]
    if price_6m_ago <= 0:
        return None
    rel_strength = (price - price_6m_ago) / price_6m_ago * 100.0

    return {
        "symbol": symbol,
        "rel_strength": rel_strength,
        "price": price,
        "avg_dollar_vol": avg_dollar_vol,
        "atr_pct": atr_pct,
    }


def scan_universe(broker) -> list[str]:
    """Scan and build the full trading universe.

    Returns the combined list of Core ETFs + top dynamic stocks.
    Fetches bar data in batches to minimize API calls and avoid rate limits.

    Parameters
    ----------
    broker : BrokerBase - broker instance for fetching data

    Returns
    -------
    list[str] : symbol list
    """
    universe = list(cfg.CORE_ETFS)
    core_set = set(universe)

    # Filter out symbols already in the core ETFs
    scan_symbols = [s for s in SP500_SYMBOLS if s not in core_set]

    logger.info("Scanning dynamic universe from %d S&P 500 candidates...", len(scan_symbols))

    # Fetch bars in batches to avoid rate limiting
    candidates = []
    for i in range(0, len(scan_symbols), _BATCH_SIZE):
        batch = scan_symbols[i : i + _BATCH_SIZE]
        logger.debug("Fetching batch %d-%d of %d symbols", i, i + len(batch), len(scan_symbols))

        try:
            bars_map = broker.get_bars_batch(batch, "1Day", 252)
        except Exception as e:
            logger.warning("Batch fetch failed for symbols %d-%d: %s", i, i + len(batch), e)
            continue

        for symbol in batch:
            bars = bars_map.get(symbol)
            if bars is None:
                continue
            try:
                candidate = _evaluate_symbol(symbol, bars)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as e:
                logger.debug("Skipping %s during universe scan: %s", symbol, e)
                continue

    # Sort by relative strength and take top N
    candidates.sort(key=lambda x: x["rel_strength"], reverse=True)
    top_n = candidates[: cfg.DYNAMIC_UNIVERSE_SIZE]

    for c in top_n:
        universe.append(c["symbol"])

    logger.info(
        "Universe scan complete: %d core ETFs + %d dynamic = %d total",
        len(cfg.CORE_ETFS), len(top_n), len(universe),
    )

    if top_n:
        logger.info(
            "Top 5 by RS: %s",
            ", ".join(f"{c['symbol']}({c['rel_strength']:+.1f}%)" for c in top_n[:5]),
        )

    return universe
