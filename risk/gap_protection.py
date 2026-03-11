"""Gap Risk Protection & Black Swan Circuit Breakers.

Handles overnight gaps that blow past stops, flash crashes, and
extreme market dislocations. These scenarios are invisible to
standard stop-loss orders (which only trigger during market hours
at the stop price — gaps skip right past them).

Rules:
  1. Gap detection: if open gaps > 5×ATR past stop, exit at market immediately
  2. Max loss cap: no single position can lose more than 3× initial risk
  3. Portfolio gap check: if total unrealized loss > 5% at open, reduce all by 50%
  4. Flash crash filter: if price drops > 10% in a single bar, do NOT sell
     (wait for bounce — flash crashes typically recover within minutes)
"""

import logging
from dataclasses import dataclass

import pandas as pd

from analysis.cest_indicators import ATR
from config import cest_settings as cfg

logger = logging.getLogger(__name__)

# Gap protection thresholds
GAP_ATR_MULTIPLIER = 5.0        # Gap > 5×ATR = blown stop
MAX_LOSS_R_MULTIPLE = 3.0       # Cap single-position loss at 3R
PORTFOLIO_GAP_LOSS_PCT = 5.0    # Emergency if portfolio down 5% at open
FLASH_CRASH_THRESHOLD_PCT = 10.0  # Don't sell into 10%+ single-bar drops


@dataclass
class GapCheckResult:
    """Result of gap risk analysis for a position."""
    action: str             # 'EXIT', 'HOLD', 'REDUCE'
    reason: str
    severity: str           # 'NORMAL', 'WARNING', 'CRITICAL'
    gap_atr_multiple: float  # how many ATRs the gap represents


def check_position_gap_risk(
    trade: "TradeRecord",
    current_open: float,
    current_close: float,
    prev_close: float,
    atr_val: float,
) -> GapCheckResult:
    """Check if a position has been hit by an adverse overnight gap.

    Parameters
    ----------
    trade        : TradeRecord - the open trade
    current_open : float - today's open price
    current_close: float - today's close (or current) price
    prev_close   : float - previous day's close
    atr_val      : float - current ATR(20) value

    Returns
    -------
    GapCheckResult with recommended action
    """
    if atr_val <= 0:
        return GapCheckResult("HOLD", "ATR invalid", "NORMAL", 0.0)

    is_long = trade.direction == "LONG"

    # Calculate gap size in ATR multiples
    gap = abs(current_open - prev_close)
    gap_atr = gap / atr_val

    # Check if gap blew past our stop
    if is_long:
        gap_adverse = current_open < trade.stop_loss
        single_bar_crash = prev_close > 0 and (prev_close - current_close) / prev_close * 100 > FLASH_CRASH_THRESHOLD_PCT
    else:
        gap_adverse = current_open > trade.stop_loss
        single_bar_crash = prev_close > 0 and (current_close - prev_close) / prev_close * 100 > FLASH_CRASH_THRESHOLD_PCT

    # 1. Blown stop (HIGHEST PRIORITY): gap jumped past stop by > 5×ATR
    #    Even in a flash crash, if our stop was blown we must exit to cap losses.
    if gap_adverse and gap_atr > GAP_ATR_MULTIPLIER:
        logger.critical(
            "BLOWN STOP %s: gap=%.1f ATR past stop | Open=%.2f Stop=%.2f | "
            "Exiting at market",
            trade.symbol, gap_atr, current_open, trade.stop_loss,
        )
        return GapCheckResult(
            "EXIT",
            f"Blown stop: gap {gap_atr:.1f}×ATR past stop",
            "CRITICAL",
            gap_atr,
        )

    # Max loss cap: if unrealized loss > 3× initial risk, exit
    if trade.initial_risk > 0:
        if is_long:
            unrealized_r = (trade.entry_price - current_close) / trade.initial_risk
        else:
            unrealized_r = (current_close - trade.entry_price) / trade.initial_risk

        if unrealized_r > MAX_LOSS_R_MULTIPLE:
            logger.warning(
                "MAX LOSS CAP %s: unrealized=%.1fR > %.1fR cap | Exiting",
                trade.symbol, unrealized_r, MAX_LOSS_R_MULTIPLE,
            )
            return GapCheckResult(
                "EXIT",
                f"Max loss cap: {unrealized_r:.1f}R > {MAX_LOSS_R_MULTIPLE}R limit",
                "CRITICAL",
                gap_atr,
            )

    # Flash crash filter: don't sell into a crash (likely to bounce)
    # Only applies when stop was NOT blown and loss is within 3R cap.
    if single_bar_crash:
        logger.warning(
            "FLASH CRASH detected for %s — holding (>%.0f%% single-bar move). "
            "Will re-evaluate next bar.",
            trade.symbol, FLASH_CRASH_THRESHOLD_PCT,
        )
        return GapCheckResult(
            "HOLD",
            f"Flash crash detected (>{FLASH_CRASH_THRESHOLD_PCT}% move) — holding for bounce",
            "WARNING",
            gap_atr,
        )

    # Normal gap — no action needed
    if gap_adverse:
        return GapCheckResult(
            "HOLD",
            f"Minor adverse gap ({gap_atr:.1f}×ATR) — within tolerance",
            "WARNING",
            gap_atr,
        )

    return GapCheckResult("HOLD", "No adverse gap", "NORMAL", gap_atr)


def check_portfolio_gap_risk(
    equity: float,
    positions: list[dict],
) -> tuple[bool, float]:
    """Check if the entire portfolio has gapped adversely at market open.

    Parameters
    ----------
    equity    : float - current account equity
    positions : list of position dicts with 'unrealized_pl' key

    Returns
    -------
    tuple[bool, float] : (emergency_triggered, total_loss_pct)
    """
    if equity <= 0 or not positions:
        return False, 0.0

    total_unrealized = sum(
        float(p.get("unrealized_pl", 0)) for p in positions
    )
    loss_pct = abs(total_unrealized) / equity * 100 if total_unrealized < 0 else 0.0

    if loss_pct > PORTFOLIO_GAP_LOSS_PCT:
        logger.critical(
            "PORTFOLIO GAP RISK: unrealized loss %.1f%% > %.1f%% threshold | "
            "Recommend reducing all positions by 50%%",
            loss_pct, PORTFOLIO_GAP_LOSS_PCT,
        )
        return True, loss_pct

    return False, loss_pct
