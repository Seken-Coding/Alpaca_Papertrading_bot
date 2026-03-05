"""CEST Position Sizing.

Fixed-fractional sizing with conviction, volatility, regime, and drawdown multipliers.
Risk is capped at 2% of equity per trade.
"""

import logging

from config import cest_settings as cfg

logger = logging.getLogger(__name__)


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_distance: float,
    regime: str,
    confluence_score: int,
    has_vcp: bool,
    atr_percentile: float,
    drawdown_multiplier: float,
) -> int:
    """Calculate the number of shares to buy/sell.

    Parameters
    ----------
    equity             : float - current account equity
    entry_price        : float - planned entry price
    stop_distance      : float - |entry - stop| in dollars per share
    regime             : str - current market regime
    confluence_score   : int - number of entry conditions met
    has_vcp            : bool - whether VCP pattern detected
    atr_percentile     : float - ATR percentile (0-100)
    drawdown_multiplier: float - from drawdown circuit breaker (0.0-1.0)

    Returns
    -------
    int : number of shares (minimum 1)
    """
    if equity <= 0 or stop_distance <= 0 or entry_price <= 0:
        logger.warning(
            "Invalid sizing inputs: equity=%.2f, stop_dist=%.2f, price=%.2f",
            equity, stop_distance, entry_price,
        )
        return 1

    # Base risk: 1% of equity
    risk_dollars = equity * cfg.RISK_PER_TRADE
    base_shares = risk_dollars / abs(stop_distance)

    # Conviction multiplier (trend trades only)
    conviction = 1.0
    if confluence_score == 5:
        conviction = 0.75
    elif confluence_score >= 6 and has_vcp:
        conviction = 1.25
    # else 1.0

    # Volatility multiplier
    if atr_percentile < 25:
        vol_mult = 1.25
    elif atr_percentile < 75:
        vol_mult = 1.0
    elif atr_percentile < 90:
        vol_mult = 0.5
    else:
        vol_mult = 0.25

    # Regime multiplier
    regime_mult_map = {
        "TREND_UP": 1.0,
        "TREND_DOWN": 1.0,
        "RANGE": 0.5,
        "HIGH_VOL": 0.25,
        "CRISIS": 0.25,
    }
    r_mult = regime_mult_map.get(regime, 0.5)

    # Final calculation
    shares = base_shares * conviction * vol_mult * r_mult * drawdown_multiplier

    # Cap at 2% max risk
    max_shares = (equity * cfg.MAX_RISK_PER_TRADE) / abs(stop_distance)
    shares = min(shares, max_shares)

    result = max(int(shares), 1)  # Floor at 1 share

    logger.info(
        "Position size: %d shares | Base=%.0f | Conv=%.2f | Vol=%.2f | "
        "Regime=%s(%.2f) | DD=%.2f | Max=%d",
        result, base_shares, conviction, vol_mult,
        regime, r_mult, drawdown_multiplier, int(max_shares),
    )

    return result
