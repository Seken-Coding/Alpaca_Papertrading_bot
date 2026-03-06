"""Risk management layer for the Alpaca Paper Trading Bot.

Design philosophy
-----------------
Every trade must pass three independent gates before being allowed:

  1. Portfolio gate   – Are total positions, daily P/L, and drawdown within limits?
  2. Signal gate      – Does the composite score meet the minimum threshold?
  3. Trade gate       – Is the calculated position size valid and R:R acceptable?

Position sizing uses ATR-based fixed-fractional risk:
  dollar_risk   = equity × risk_per_trade_pct        (e.g. 1% of $100k = $1,000)
  stop_distance = ATR × atr_stop_multiplier           (e.g. 2× daily ATR)
  shares        = dollar_risk / stop_distance
  → capped at max_position_pct × equity / price

This approach keeps every trade's loss, *if stopped out*, to a defined fraction
of equity — so a string of losers cannot blow up the account.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)
risk_logger = logging.getLogger("risk")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskConfig:
    """All tunable risk parameters in one place.

    Every field can be overridden via an environment variable (set in .env).
    Defaults are conservative values suitable for paper trading.

    Environment variables (all optional):
        MAX_POSITION_PCT      float  (default 0.05)   Max 5% of equity per position
        RISK_PER_TRADE_PCT    float  (default 0.01)   Risk 1% of equity per trade
        ATR_STOP_MULTIPLIER   float  (default 2.0)    Stop placed 2×ATR from entry
        MIN_RISK_REWARD       float  (default 1.5)    Min acceptable R:R ratio
        MAX_POSITIONS         int    (default 10)     Max concurrent positions
        MIN_BUYING_POWER      float  (default 500.0)  Min $ buying power
        MAX_DAILY_LOSS_PCT    float  (default 0.03)   Halt if down 3% on the day
        MAX_DRAWDOWN_PCT      float  (default 0.10)   Halt if down 10% from peak
        MIN_SCORE_THRESHOLD   float  (default 62.0)   Min signal strength (0-100)
    """

    # ── Position sizing ──────────────────────────────────────────────
    max_position_pct: float    = 0.05
    risk_per_trade_pct: float  = 0.01
    atr_stop_multiplier: float = 2.0
    min_risk_reward: float     = 1.5

    # ── Portfolio limits ─────────────────────────────────────────────
    max_positions: int         = 10
    min_buying_power: float    = 500.0

    # ── Daily / drawdown circuit breakers ────────────────────────────
    max_daily_loss_pct: float  = 0.03
    max_drawdown_pct: float    = 0.10

    # ── Signal quality filter ────────────────────────────────────────
    min_score_threshold: float = 62.0

    def __post_init__(self):
        """Override defaults with environment variables if set."""
        env_map = {
            "MAX_POSITION_PCT": ("max_position_pct", float),
            "RISK_PER_TRADE_PCT": ("risk_per_trade_pct", float),
            "ATR_STOP_MULTIPLIER": ("atr_stop_multiplier", float),
            "MIN_RISK_REWARD": ("min_risk_reward", float),
            "MAX_POSITIONS": ("max_positions", int),
            "MIN_BUYING_POWER": ("min_buying_power", float),
            "MAX_DAILY_LOSS_PCT": ("max_daily_loss_pct", float),
            "MAX_DRAWDOWN_PCT": ("max_drawdown_pct", float),
            "MIN_SCORE_THRESHOLD": ("min_score_threshold", float),
        }
        for env_key, (attr, cast) in env_map.items():
            val = os.getenv(env_key)
            if val is not None:
                setattr(self, attr, cast(val))


# ─────────────────────────────────────────────────────────────────────────────
# Result objects
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PositionSizeResult:
    """Outcome of a position-size calculation."""
    symbol:           str
    price:            float
    atr:              float
    shares:           int
    notional:         float    # shares × price
    dollar_risk:      float    # shares × stop_distance (max loss if stopped out)
    stop_loss_price:  float
    take_profit_price: float
    risk_reward:      float
    passes_risk:      bool
    rejection_reason: str = ""

    def summary(self) -> str:
        if not self.passes_risk:
            return f"REJECTED — {self.rejection_reason}"
        return (
            f"{self.shares} shares × ${self.price:.2f} = ${self.notional:.0f} notional | "
            f"Risk ${self.dollar_risk:.0f} | SL ${self.stop_loss_price:.2f} | "
            f"TP ${self.take_profit_price:.2f} | R:R {self.risk_reward:.2f}"
        )


@dataclass
class RiskCheckResult:
    """Outcome of a portfolio-level risk check."""
    allowed:  bool
    reason:   str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Risk Manager
# ─────────────────────────────────────────────────────────────────────────────

class RiskManager:
    """Stateful risk manager — tracks equity curve and enforces all risk rules.

    Typical usage
    -------------
    rm = RiskManager()

    # Once at session start (after fetching account):
    rm.set_session_equity(float(account.equity))

    # Before any trade:
    check = rm.check_portfolio_limits(len(positions), equity, buying_power)
    if check.allowed:
        sizing = rm.calculate_position_size(symbol, price, atr, equity, "BUY")
        if sizing.passes_risk:
            client.bracket_order(symbol, sizing.shares, side,
                                 sizing.take_profit_price, sizing.stop_loss_price)

    # After each refresh:
    rm.update_equity(float(account.equity))
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self._peak_equity:          float = 0.0
        self._session_start_equity: float = 0.0
        self._session_date:         Optional[date] = None

    # ── Session tracking ──────────────────────────────────────────────────

    def set_session_equity(self, equity: float) -> None:
        """Record the equity at session start. Call once after connecting."""
        today = date.today()
        if self._session_date != today:
            self._session_start_equity = equity
            self._session_date = today
            risk_logger.info(
                "Session start — equity $%.2f | date %s", equity, today
            )
        if equity > self._peak_equity:
            self._peak_equity = equity

    def update_equity(self, equity: float) -> None:
        """Update running equity; advances the peak and tracks drawdown."""
        if equity > self._peak_equity:
            self._peak_equity = equity
            risk_logger.debug("New equity peak: $%.2f", equity)

    # ── Portfolio-level gate ──────────────────────────────────────────────

    def check_portfolio_limits(
        self,
        position_count: int,
        equity: float,
        buying_power: float,
    ) -> RiskCheckResult:
        """Return (allowed, reason). Call before calculating position size."""

        # 1. Max open positions
        if position_count >= self.config.max_positions:
            msg = (
                f"Max positions reached ({position_count}/{self.config.max_positions})"
            )
            risk_logger.warning("TRADE BLOCKED — %s", msg)
            return RiskCheckResult(False, msg)

        # 2. Minimum buying power
        if buying_power < self.config.min_buying_power:
            msg = f"Insufficient buying power (${buying_power:.0f} < ${self.config.min_buying_power:.0f})"
            risk_logger.warning("TRADE BLOCKED — %s", msg)
            return RiskCheckResult(False, msg)

        # 3. Daily loss circuit breaker
        if self._session_start_equity > 0:
            daily_pnl_pct = (equity - self._session_start_equity) / self._session_start_equity
            if daily_pnl_pct <= -self.config.max_daily_loss_pct:
                msg = (
                    f"Daily loss limit hit ({daily_pnl_pct:.2%} ≤ "
                    f"-{self.config.max_daily_loss_pct:.2%})"
                )
                risk_logger.warning("TRADING HALTED — %s", msg)
                return RiskCheckResult(False, msg)

        # 4. Max drawdown circuit breaker
        if self._peak_equity > 0:
            drawdown_pct = (self._peak_equity - equity) / self._peak_equity
            if drawdown_pct >= self.config.max_drawdown_pct:
                msg = (
                    f"Max drawdown hit ({drawdown_pct:.2%} ≥ "
                    f"{self.config.max_drawdown_pct:.2%})"
                )
                risk_logger.warning("TRADING HALTED — %s", msg)
                return RiskCheckResult(False, msg)

        return RiskCheckResult(True)

    # ── Signal quality gate ───────────────────────────────────────────────

    def validate_score(self, composite_score: float) -> RiskCheckResult:
        """Check whether the signal's composite score meets the minimum."""
        if composite_score < self.config.min_score_threshold:
            msg = (
                f"Score {composite_score:.1f} below minimum "
                f"{self.config.min_score_threshold:.1f}"
            )
            risk_logger.info("Signal filtered — %s", msg)
            return RiskCheckResult(False, msg)
        return RiskCheckResult(True)

    # ── Position sizing gate ──────────────────────────────────────────────

    def calculate_position_size(
        self,
        symbol: str,
        price: float,
        atr: float,
        equity: float,
        direction: str = "BUY",
    ) -> PositionSizeResult:
        """Compute ATR-based position size.

        Formula
        -------
        dollar_risk   = equity × risk_per_trade_pct
        stop_distance = atr × atr_stop_multiplier
        shares        = floor(dollar_risk / stop_distance)
        capped at     = floor(equity × max_position_pct / price)
        """
        def _reject(reason: str) -> PositionSizeResult:
            risk_logger.warning("Position size REJECTED for %s — %s", symbol, reason)
            return PositionSizeResult(
                symbol=symbol, price=price, atr=atr,
                shares=0, notional=0.0, dollar_risk=0.0,
                stop_loss_price=price, take_profit_price=price,
                risk_reward=0.0, passes_risk=False, rejection_reason=reason,
            )

        if price <= 0:
            return _reject("Invalid price (≤ 0)")
        if atr <= 0:
            return _reject("Invalid ATR (≤ 0)")
        if equity <= 0:
            return _reject("Invalid equity (≤ 0)")

        dollar_risk    = equity * self.config.risk_per_trade_pct
        stop_distance  = atr * self.config.atr_stop_multiplier
        max_notional   = equity * self.config.max_position_pct

        shares_by_risk = int(dollar_risk / stop_distance)
        shares_by_pct  = int(max_notional / price)
        shares = min(shares_by_risk, shares_by_pct)

        if shares <= 0:
            return _reject(
                f"Shares computed as zero (equity ${equity:.0f}, ATR "
                f"${atr:.2f}, price ${price:.2f})"
            )

        notional     = shares * price
        actual_risk  = shares * stop_distance

        # Stop and target prices
        if direction.upper() == "BUY":
            stop_loss_price   = round(price - stop_distance, 2)
            take_profit_price = round(price + stop_distance * self.config.min_risk_reward, 2)
        else:
            stop_loss_price   = round(price + stop_distance, 2)
            take_profit_price = round(price - stop_distance * self.config.min_risk_reward, 2)

        reward   = abs(take_profit_price - price)
        risk_leg = abs(stop_loss_price - price)
        rr = round(reward / risk_leg, 2) if risk_leg > 0 else 0.0

        passes = rr >= self.config.min_risk_reward
        reason = (
            "" if passes
            else f"R:R {rr:.2f} below minimum {self.config.min_risk_reward:.2f}"
        )

        result = PositionSizeResult(
            symbol=symbol, price=price, atr=atr,
            shares=shares, notional=round(notional, 2),
            dollar_risk=round(actual_risk, 2),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_reward=rr, passes_risk=passes,
            rejection_reason=reason,
        )
        risk_logger.info(
            "PositionSize %s: %s",
            symbol, result.summary()
        )
        return result

    # ── State queries ─────────────────────────────────────────────────────

    def get_risk_summary(self, equity: float) -> dict:
        """Return a dict of current risk metrics suitable for GUI display."""
        if self._session_start_equity > 0:
            daily_pnl      = equity - self._session_start_equity
            daily_pnl_pct  = daily_pnl / self._session_start_equity
            daily_loss_used_pct = max(0.0, -daily_pnl_pct) / self.config.max_daily_loss_pct
        else:
            daily_pnl = daily_pnl_pct = daily_loss_used_pct = 0.0

        if self._peak_equity > 0:
            drawdown_pct      = (self._peak_equity - equity) / self._peak_equity
            drawdown_used_pct = drawdown_pct / self.config.max_drawdown_pct
        else:
            drawdown_pct = drawdown_used_pct = 0.0

        trading_allowed = (
            daily_pnl_pct > -self.config.max_daily_loss_pct
            and drawdown_pct < self.config.max_drawdown_pct
        )

        return {
            "equity":               equity,
            "peak_equity":          self._peak_equity,
            "session_start_equity": self._session_start_equity,
            "daily_pnl":            daily_pnl,
            "daily_pnl_pct":        daily_pnl_pct,
            "daily_loss_used_pct":  min(daily_loss_used_pct, 1.0),
            "drawdown_pct":         drawdown_pct,
            "drawdown_used_pct":    min(drawdown_used_pct, 1.0),
            "trading_allowed":      trading_allowed,
            "max_daily_loss_pct":   self.config.max_daily_loss_pct,
            "max_drawdown_pct":     self.config.max_drawdown_pct,
        }

    @property
    def daily_pnl(self) -> float:
        """Convenience accessor (requires equity to be updated externally)."""
        return 0.0  # Returned via get_risk_summary with live equity
