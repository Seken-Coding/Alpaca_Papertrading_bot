"""CEST Risk Manager — Portfolio constraints, drawdown breakers, equity curve filter.

Enforces:
  - Max positions (10)
  - Max same-direction positions (6)
  - Max sector positions (3)
  - Correlation threshold (0.70 per pair, 0.50 avg portfolio)
  - Drawdown circuit breakers (5%, 10%, 15%, 20%)
  - Equity curve filter (50-trade SMA)
"""

import logging

import numpy as np
import pandas as pd

from config import cest_settings as cfg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Drawdown Circuit Breakers
# ---------------------------------------------------------------------------

def get_drawdown_multiplier(current_equity: float, peak_equity: float) -> float:
    """Return a position-size multiplier based on drawdown from peak.

    Returns
    -------
    float : 0.0 (halt), 0.25, 0.50, 0.75, or 1.0
    """
    if peak_equity <= 0:
        return 1.0

    drawdown_pct = (peak_equity - current_equity) / peak_equity * 100.0

    if drawdown_pct >= cfg.DD_HALT:
        logger.critical("DRAWDOWN HALT: %.1f%% >= %d%% — all trading halted", drawdown_pct, cfg.DD_HALT)
        return 0.0
    elif drawdown_pct >= cfg.DD_REDUCE_75:
        logger.warning("Drawdown %.1f%% — reducing to 25%% size", drawdown_pct)
        return 0.25
    elif drawdown_pct >= cfg.DD_REDUCE_50:
        logger.warning("Drawdown %.1f%% — reducing to 50%% size", drawdown_pct)
        return 0.50
    elif drawdown_pct >= cfg.DD_WARNING:
        logger.info("Drawdown %.1f%% — reducing to 75%% size", drawdown_pct)
        return 0.75

    return 1.0


# ---------------------------------------------------------------------------
# Equity Curve Filter
# ---------------------------------------------------------------------------

def passes_equity_curve_filter(trade_results: list[float]) -> bool:
    """Check if equity curve is above its 50-trade SMA.

    If equity curve drops below SMA, reduce size.
    Below 100-trade SMA, halt entirely.

    Parameters
    ----------
    trade_results : list[float] - list of P&L per trade

    Returns
    -------
    bool : True if trading is allowed at full size
    """
    if len(trade_results) < cfg.EQUITY_SMA_PERIOD:
        return True  # Not enough data yet

    equity_curve = np.cumsum(trade_results)
    sma_period = cfg.EQUITY_SMA_PERIOD
    sma = np.convolve(equity_curve, np.ones(sma_period) / sma_period, mode="valid")

    if len(sma) == 0:
        return True

    if equity_curve[-1] < sma[-1]:
        logger.warning(
            "Equity curve (%.2f) below %d-trade SMA (%.2f) — reducing size",
            equity_curve[-1], sma_period, sma[-1],
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Correlation Matrix
# ---------------------------------------------------------------------------

def calculate_correlation_matrix(
    price_data: dict[str, pd.Series],
    lookback: int = None,
) -> pd.DataFrame:
    """Calculate correlation matrix on daily returns.

    Parameters
    ----------
    price_data : dict mapping symbol -> close price series
    lookback   : int - number of days (default: CORRELATION_LOOKBACK)

    Returns
    -------
    pd.DataFrame : correlation matrix
    """
    lookback = lookback or cfg.CORRELATION_LOOKBACK

    returns = {}
    for symbol, prices in price_data.items():
        if len(prices) < lookback + 1:
            continue
        daily_returns = prices.pct_change().dropna().tail(lookback)
        if len(daily_returns) >= lookback * 0.8:  # Allow some missing data
            returns[symbol] = daily_returns

    if len(returns) < 2:
        return pd.DataFrame()

    returns_df = pd.DataFrame(returns)
    return returns_df.corr()


def check_correlation_filter(
    new_symbol: str,
    open_symbols: list[str],
    price_data: dict[str, pd.Series],
) -> bool:
    """Check if adding new_symbol passes correlation constraints.

    Blocks if:
    - Correlation with any open position > 0.70
    - Average portfolio correlation would exceed 0.50

    Returns
    -------
    bool : True if the position is allowed
    """
    if not open_symbols:
        return True

    # Need price data for the new symbol and at least one open symbol
    all_symbols = [s for s in open_symbols if s in price_data]
    if new_symbol not in price_data or not all_symbols:
        return True  # Can't compute — allow

    all_symbols_with_new = all_symbols + [new_symbol]
    subset = {s: price_data[s] for s in all_symbols_with_new}
    corr_matrix = calculate_correlation_matrix(subset)

    if corr_matrix.empty or new_symbol not in corr_matrix.columns:
        return True

    # Check pairwise correlation with each open position
    for sym in all_symbols:
        if sym in corr_matrix.columns:
            pair_corr = abs(corr_matrix.loc[new_symbol, sym])
            if pair_corr > cfg.CORRELATION_THRESHOLD:
                logger.info(
                    "Correlation filter blocked %s: corr with %s = %.2f > %.2f",
                    new_symbol, sym, pair_corr, cfg.CORRELATION_THRESHOLD,
                )
                return False

    # Check average portfolio correlation
    if len(all_symbols_with_new) >= 3:
        portfolio_subset = {s: price_data[s] for s in all_symbols_with_new}
        full_corr = calculate_correlation_matrix(portfolio_subset)
        if not full_corr.empty:
            # Average of off-diagonal correlations
            n = len(full_corr)
            if n > 1:
                total = full_corr.values.sum() - n  # subtract diagonal (1s)
                avg_corr = abs(total) / (n * (n - 1))
                if avg_corr > cfg.PORTFOLIO_CORR_LIMIT:
                    logger.info(
                        "Portfolio correlation filter blocked %s: avg corr = %.2f > %.2f",
                        new_symbol, avg_corr, cfg.PORTFOLIO_CORR_LIMIT,
                    )
                    return False

    return True


# ---------------------------------------------------------------------------
# Portfolio Constraints
# ---------------------------------------------------------------------------

def passes_portfolio_filter(
    symbol: str,
    direction: str,
    open_positions: list[dict],
    price_data: dict[str, pd.Series],
) -> tuple[bool, str]:
    """Check all portfolio-level constraints before opening a new position.

    Parameters
    ----------
    symbol         : str - new symbol to trade
    direction      : str - 'LONG' or 'SHORT'
    open_positions : list of dicts with 'symbol', 'side' keys
    price_data     : dict mapping symbol -> close prices for correlation

    Returns
    -------
    tuple[bool, str] : (passes, reason_if_blocked)
    """
    # Max positions
    if len(open_positions) >= cfg.MAX_POSITIONS:
        return False, f"Max positions ({cfg.MAX_POSITIONS}) reached"

    # Max same direction
    same_dir_count = sum(
        1 for p in open_positions
        if p.get("side", "").upper() == direction
    )
    if same_dir_count >= cfg.MAX_SAME_DIRECTION:
        return False, f"Max {direction} positions ({cfg.MAX_SAME_DIRECTION}) reached"

    # Max sector
    new_sector = cfg.SECTOR_MAP.get(symbol, cfg.DEFAULT_SECTOR)
    sector_count = sum(
        1 for p in open_positions
        if cfg.SECTOR_MAP.get(p["symbol"], cfg.DEFAULT_SECTOR) == new_sector
    )
    if sector_count >= cfg.MAX_SECTOR_POSITIONS:
        return False, f"Max sector positions ({cfg.MAX_SECTOR_POSITIONS}) for {new_sector}"

    # Correlation filter
    open_symbols = [p["symbol"] for p in open_positions]
    if not check_correlation_filter(symbol, open_symbols, price_data):
        return False, "Correlation filter blocked"

    return True, ""
