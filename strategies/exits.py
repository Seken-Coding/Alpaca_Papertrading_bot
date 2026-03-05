"""CEST Exit Logic.

Manages all exit conditions for open trades:
  - Initial stop-loss
  - Chandelier trailing stop (trend trades)
  - Profit targets with partial exits
  - Time-based exits
  - Breakeven rule
  - RSI-based exits (mean-reversion)
"""

import logging
from dataclasses import dataclass

import pandas as pd

from analysis.cest_indicators import ATR, RSI
from config import cest_settings as cfg

logger = logging.getLogger(__name__)


@dataclass
class ExitAction:
    """Describes an exit action to take."""
    symbol: str
    action: str           # 'FULL_EXIT', 'PARTIAL_EXIT', 'ADJUST_STOP'
    reason: str           # exit reason code
    exit_price: float     # suggested exit price (current close)
    new_stop: float | None = None  # for ADJUST_STOP
    partial_pct: float = 1.0       # fraction to exit (0.5 for half)


def manage_exits(
    trade: "TradeRecord",
    data: pd.DataFrame,
    regime: str,
) -> ExitAction | None:
    """Evaluate all exit conditions for an open trade.

    Parameters
    ----------
    trade  : TradeRecord - the open trade (from utils/trade_tracker.py)
    data   : pd.DataFrame - OHLCV data
    regime : str - current regime

    Returns
    -------
    ExitAction or None if no exit triggered
    """
    if len(data) < cfg.ATR_PERIOD + 1:
        return None

    close = data["close"]
    high = data["high"]
    low = data["low"]
    price = close.iloc[-1]

    atr_series = ATR(high, low, close, period=cfg.ATR_PERIOD)
    atr_val = atr_series.iloc[-1]
    if pd.isna(atr_val):
        return None

    is_long = trade.direction == "LONG"
    is_trend = trade.strategy_type == "TREND"

    # Calculate current R-multiple
    if trade.initial_risk <= 0:
        return None
    if is_long:
        current_r = (price - trade.entry_price) / trade.initial_risk
    else:
        current_r = (trade.entry_price - price) / trade.initial_risk

    # Update highest/lowest close since entry
    # (These should be maintained by the trade tracker on each bar)

    # --- Check exits in priority order ---

    # 1. STOP-LOSS CHECK
    stop_hit = _check_stop_loss(trade, price, is_long)
    if stop_hit:
        return ExitAction(
            symbol=trade.symbol,
            action="FULL_EXIT",
            reason="STOP_LOSS",
            exit_price=price,
        )

    # 2. TIME-BASED EXIT
    time_exit = _check_time_exit(trade, is_trend)
    if time_exit:
        return time_exit

    # 3. MEAN-REVERSION RSI EXIT
    if not is_trend:
        rsi_exit = _check_mr_rsi_exit(trade, close, is_long)
        if rsi_exit:
            return rsi_exit

    # 4. MEAN-REVERSION TARGET
    if not is_trend and current_r >= cfg.MR_TARGET_R:
        return ExitAction(
            symbol=trade.symbol,
            action="FULL_EXIT",
            reason="TARGET",
            exit_price=price,
        )

    # 5. TREND PARTIAL PROFIT (50% at 3R)
    if is_trend and not trade.partial_taken and current_r >= cfg.TREND_PARTIAL_PROFIT_R:
        logger.info(
            "PARTIAL EXIT %s at %.1fR | Price=%.2f",
            trade.symbol, current_r, price,
        )
        return ExitAction(
            symbol=trade.symbol,
            action="PARTIAL_EXIT",
            reason="TARGET",
            exit_price=price,
            partial_pct=cfg.TREND_PARTIAL_SIZE,
        )

    # 6. BREAKEVEN RULE
    if is_trend and not trade.breakeven_triggered and current_r >= cfg.BREAKEVEN_TRIGGER_R:
        logger.info(
            "BREAKEVEN triggered %s at %.1fR | Moving stop to entry %.2f",
            trade.symbol, current_r, trade.entry_price,
        )
        return ExitAction(
            symbol=trade.symbol,
            action="ADJUST_STOP",
            reason="BREAKEVEN",
            exit_price=price,
            new_stop=trade.entry_price,
        )

    # 7. CHANDELIER TRAILING STOP (trend trades only, after breakeven)
    if is_trend and trade.breakeven_triggered:
        chandelier = _chandelier_stop(trade, data, atr_val, is_long)
        if chandelier:
            return chandelier

    return None


def _check_stop_loss(trade: "TradeRecord", price: float, is_long: bool) -> bool:
    """Check if current price has hit the stop-loss."""
    if is_long:
        return price <= trade.stop_loss
    else:
        return price >= trade.stop_loss


def _check_time_exit(
    trade: "TradeRecord",
    is_trend: bool,
) -> ExitAction | None:
    """Check time-based exit conditions."""
    bars_held = trade.bars_held or 0
    max_bars = cfg.TREND_TIME_STOP_BARS if is_trend else cfg.MR_TIME_STOP_BARS

    is_long = trade.direction == "LONG"

    if is_trend:
        # Trend: exit if NOT moved 1R in expected direction within 10 bars
        if bars_held >= max_bars:
            if trade.initial_risk > 0:
                if is_long:
                    best_r = ((trade.highest_close_since_entry or trade.entry_price) - trade.entry_price) / trade.initial_risk
                else:
                    best_r = (trade.entry_price - (trade.lowest_close_since_entry or trade.entry_price)) / trade.initial_risk
                if best_r < 1.0:
                    return ExitAction(
                        symbol=trade.symbol,
                        action="FULL_EXIT",
                        reason="TIME_EXIT",
                        exit_price=trade.entry_price,  # will be filled at market
                    )
    else:
        # Mean-reversion: max hold = 5 bars
        if bars_held >= max_bars:
            return ExitAction(
                symbol=trade.symbol,
                action="FULL_EXIT",
                reason="TIME_EXIT",
                exit_price=trade.entry_price,
            )

    return None


def _check_mr_rsi_exit(
    trade: "TradeRecord",
    close: pd.Series,
    is_long: bool,
) -> ExitAction | None:
    """Mean-reversion RSI exit: RSI(3) crosses threshold."""
    rsi3 = RSI(close, cfg.RSI_SHORT_PERIOD)
    rsi3_val = rsi3.iloc[-1]
    if pd.isna(rsi3_val):
        return None

    if is_long and rsi3_val > cfg.MR_RSI_EXIT_LONG:
        return ExitAction(
            symbol=trade.symbol,
            action="FULL_EXIT",
            reason="RSI_EXIT",
            exit_price=close.iloc[-1],
        )

    if not is_long and rsi3_val < cfg.MR_RSI_EXIT_SHORT:
        return ExitAction(
            symbol=trade.symbol,
            action="FULL_EXIT",
            reason="RSI_EXIT",
            exit_price=close.iloc[-1],
        )

    return None


def _chandelier_stop(
    trade: "TradeRecord",
    data: pd.DataFrame,
    atr_val: float,
    is_long: bool,
) -> ExitAction | None:
    """Chandelier trailing stop: highest close since entry - 3×ATR(20).

    Never widens — only tightens.
    """
    price = data["close"].iloc[-1]

    if is_long:
        highest = trade.highest_close_since_entry or trade.entry_price
        chandelier_stop = highest - cfg.TRAILING_STOP_ATR_MULT * atr_val

        # Never widen: new stop must be >= current stop
        new_stop = max(chandelier_stop, trade.stop_loss)

        if price <= new_stop:
            return ExitAction(
                symbol=trade.symbol,
                action="FULL_EXIT",
                reason="TRAILING_STOP",
                exit_price=price,
            )

        # Tighten stop if chandelier is higher
        if new_stop > trade.stop_loss:
            return ExitAction(
                symbol=trade.symbol,
                action="ADJUST_STOP",
                reason="TRAILING_STOP",
                exit_price=price,
                new_stop=new_stop,
            )
    else:
        lowest = trade.lowest_close_since_entry or trade.entry_price
        chandelier_stop = lowest + cfg.TRAILING_STOP_ATR_MULT * atr_val

        # Never widen: new stop must be <= current stop
        new_stop = min(chandelier_stop, trade.stop_loss)

        if price >= new_stop:
            return ExitAction(
                symbol=trade.symbol,
                action="FULL_EXIT",
                reason="TRAILING_STOP",
                exit_price=price,
            )

        if new_stop < trade.stop_loss:
            return ExitAction(
                symbol=trade.symbol,
                action="ADJUST_STOP",
                reason="TRAILING_STOP",
                exit_price=price,
                new_stop=new_stop,
            )

    return None
