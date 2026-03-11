"""Backtesting Engine for CEST Strategy.

Replays historical daily bars through the full CEST pipeline:
  regime detection → signal generation → position sizing → exit management

Produces an equity curve, trade log, and performance metrics.

Usage:
    from backtest.engine import Backtester
    bt = Backtester(initial_equity=100_000)
    results = bt.run(market_data, spy_data)
    results.print_summary()
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from strategies.regime import detect_regime
from strategies.entries import generate_signal
from strategies.exits import manage_exits
from strategies.spy_macro import detect_spy_macro
from strategies.pyramiding import check_pyramid_opportunity
from risk.position_sizing import calculate_position_size
from risk.cest_risk_manager import get_drawdown_multiplier
from risk.gap_protection import check_position_gap_risk
from config import cest_settings as cfg

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Record of a completed backtest trade."""
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    entry_bar: int
    exit_bar: int
    shares: int
    pnl: float
    pnl_pct: float
    r_multiple: float
    exit_reason: str
    regime_at_entry: str
    strategy_type: str


@dataclass
class BacktestPosition:
    """An open position during backtesting."""
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    initial_risk: float
    shares: int
    entry_bar: int
    regime_at_entry: str
    strategy_type: str
    confluence_score: int
    bars_held: int = 0
    highest_close_since_entry: float = 0.0
    lowest_close_since_entry: float = float("inf")
    partial_taken: bool = False
    breakeven_triggered: bool = False
    pyramids_added: int = 0
    position_size: int = 0  # alias for shares (compatibility with TradeRecord)

    def __post_init__(self):
        self.position_size = self.shares
        self.highest_close_since_entry = self.entry_price
        self.lowest_close_since_entry = self.entry_price

    def update_bar(self, close: float):
        self.bars_held += 1
        if close > self.highest_close_since_entry:
            self.highest_close_since_entry = close
        if close < self.lowest_close_since_entry:
            self.lowest_close_since_entry = close


@dataclass
class BacktestResults:
    """Comprehensive backtest results and performance metrics."""
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    dates: list = field(default_factory=list)
    initial_equity: float = 100_000

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl <= 0)

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades * 100 if self.total_trades else 0

    @property
    def avg_winner(self) -> float:
        winners = [t.pnl for t in self.trades if t.pnl > 0]
        return np.mean(winners) if winners else 0

    @property
    def avg_loser(self) -> float:
        losers = [t.pnl for t in self.trades if t.pnl <= 0]
        return np.mean(losers) if losers else 0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl <= 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_return_pct(self) -> float:
        return self.total_pnl / self.initial_equity * 100 if self.initial_equity else 0

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0
        peak = self.equity_curve[0]
        max_dd = 0
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def sharpe_ratio(self) -> float:
        if len(self.equity_curve) < 2:
            return 0
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        if returns.std() == 0:
            return 0
        return float(returns.mean() / returns.std() * np.sqrt(252))

    @property
    def avg_r_multiple(self) -> float:
        if not self.trades:
            return 0
        return float(np.mean([t.r_multiple for t in self.trades]))

    @property
    def risk_reward_ratio(self) -> float:
        if self.avg_loser == 0:
            return float("inf")
        return abs(self.avg_winner / self.avg_loser)

    def print_summary(self):
        """Print a formatted performance summary."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(f"  Initial Equity:     ${self.initial_equity:,.2f}")
        print(f"  Final Equity:       ${self.equity_curve[-1]:,.2f}" if self.equity_curve else "  Final Equity: N/A")
        print(f"  Total P&L:          ${self.total_pnl:,.2f}")
        print(f"  Total Return:       {self.total_return_pct:.1f}%")
        print(f"  Max Drawdown:       {self.max_drawdown_pct:.1f}%")
        print(f"  Sharpe Ratio:       {self.sharpe_ratio:.2f}")
        print("-" * 60)
        print(f"  Total Trades:       {self.total_trades}")
        print(f"  Win Rate:           {self.win_rate:.1f}%")
        print(f"  Avg Winner:         ${self.avg_winner:,.2f}")
        print(f"  Avg Loser:          ${self.avg_loser:,.2f}")
        print(f"  Risk/Reward Ratio:  {self.risk_reward_ratio:.2f}")
        print(f"  Avg R-Multiple:     {self.avg_r_multiple:.2f}R")
        print(f"  Profit Factor:      {self.profit_factor:.2f}")
        print("=" * 60)

        # Performance targets check
        print("\nPerformance Targets:")
        print(f"  Win rate 45-55%:    {'PASS' if 45 <= self.win_rate <= 55 else 'MISS'} ({self.win_rate:.1f}%)")
        print(f"  R:R >= 1:2:         {'PASS' if self.risk_reward_ratio >= 2.0 else 'MISS'} ({self.risk_reward_ratio:.2f})")
        print(f"  Max DD < 20%:       {'PASS' if self.max_drawdown_pct < 20 else 'MISS'} ({self.max_drawdown_pct:.1f}%)")
        print(f"  Sharpe > 1.0:       {'PASS' if self.sharpe_ratio > 1.0 else 'MISS'} ({self.sharpe_ratio:.2f})")
        print(f"  Profit factor > 1.5:{'PASS' if self.profit_factor > 1.5 else 'MISS'} ({self.profit_factor:.2f})")


class Backtester:
    """Event-driven backtester for the CEST strategy.

    Replays daily bars symbol-by-symbol and applies the full CEST pipeline.

    Parameters
    ----------
    initial_equity : float - starting account equity
    max_positions  : int - max concurrent positions
    use_spy_macro  : bool - enable SPY macro regime overlay
    use_gap_protection : bool - enable gap risk checks
    use_pyramiding : bool - enable adding to winners
    """

    def __init__(
        self,
        initial_equity: float = 100_000,
        max_positions: int = 10,
        use_spy_macro: bool = True,
        use_gap_protection: bool = True,
        use_pyramiding: bool = True,
    ):
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.peak_equity = initial_equity
        self.max_positions = max_positions
        self.use_spy_macro = use_spy_macro
        self.use_gap_protection = use_gap_protection
        self.use_pyramiding = use_pyramiding

        self.positions: dict[str, BacktestPosition] = {}
        self.results = BacktestResults(initial_equity=initial_equity)

    def run(
        self,
        market_data: dict[str, pd.DataFrame],
        spy_data: pd.DataFrame | None = None,
        start_bar: int = 252,
    ) -> BacktestResults:
        """Run the backtest over historical data.

        Parameters
        ----------
        market_data : dict mapping symbol -> DataFrame with OHLCV columns
        spy_data    : DataFrame with SPY OHLCV (for macro filter)
        start_bar   : int - bar index to start trading (need warmup for indicators)

        Returns
        -------
        BacktestResults
        """
        # Determine the common date range across all symbols
        all_dates = set()
        for df in market_data.values():
            all_dates.update(df.index.tolist())
        all_dates = sorted(all_dates)

        if len(all_dates) <= start_bar:
            logger.warning("Insufficient data for backtest (%d bars, need %d)", len(all_dates), start_bar)
            return self.results

        logger.info(
            "Starting backtest: %d symbols, %d bars, equity=$%.0f",
            len(market_data), len(all_dates), self.equity,
        )

        for bar_idx in range(start_bar, len(all_dates)):
            date = all_dates[bar_idx]

            # Track equity
            self.results.equity_curve.append(self.equity)
            self.results.dates.append(date)

            # Update peak equity
            if self.equity > self.peak_equity:
                self.peak_equity = self.equity

            # Drawdown check
            dd_mult = get_drawdown_multiplier(self.equity, self.peak_equity)
            if dd_mult == 0:
                # Close all positions
                self._close_all(market_data, bar_idx, all_dates, "DRAWDOWN_HALT")
                continue

            # SPY macro regime
            macro_mult = 1.0
            macro_long_allowed = True
            if self.use_spy_macro and spy_data is not None and len(spy_data) > bar_idx:
                spy_slice = spy_data.iloc[:bar_idx + 1]
                if len(spy_slice) >= 201:
                    macro = detect_spy_macro(spy_slice["close"])
                    macro_mult = macro.size_multiplier
                    macro_long_allowed = macro.long_allowed

            # Process exits for open positions
            self._process_exits(market_data, bar_idx, all_dates)

            # Process pyramids for open positions
            if self.use_pyramiding:
                self._process_pyramids(market_data, bar_idx, all_dates)

            # Scan for new entries
            if len(self.positions) < self.max_positions:
                self._scan_entries(
                    market_data, bar_idx, all_dates,
                    dd_mult, macro_mult, macro_long_allowed,
                )

        # Close any remaining positions at the end
        self._close_all(market_data, len(all_dates) - 1, all_dates, "BACKTEST_END")

        # Final equity
        self.results.equity_curve.append(self.equity)

        logger.info("Backtest complete: %d trades", self.results.total_trades)
        return self.results

    def _process_exits(self, market_data, bar_idx, all_dates):
        """Check exit conditions for all open positions."""
        to_close = []

        for symbol, pos in self.positions.items():
            if symbol not in market_data:
                continue

            df = market_data[symbol]
            date = all_dates[bar_idx]
            if date not in df.index:
                continue

            loc = df.index.get_loc(date)
            if loc < cfg.ATR_PERIOD + 1:
                continue

            data_slice = df.iloc[:loc + 1]
            price = float(data_slice["close"].iloc[-1])

            # Update position tracking
            pos.update_bar(price)

            # Gap protection check
            if self.use_gap_protection and loc > 0:
                from analysis.cest_indicators import ATR as calc_atr
                atr_series = calc_atr(data_slice["high"], data_slice["low"], data_slice["close"], cfg.ATR_PERIOD)
                atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0
                if atr_val > 0:
                    gap_result = check_position_gap_risk(
                        pos,
                        float(data_slice["open"].iloc[-1]),
                        price,
                        float(data_slice["close"].iloc[-2]),
                        atr_val,
                    )
                    if gap_result.action == "EXIT":
                        to_close.append((symbol, price, gap_result.reason))
                        continue

            # Standard exit logic
            regime = detect_regime(data_slice["close"], data_slice["high"], data_slice["low"])
            exit_action = manage_exits(pos, data_slice, regime)

            if exit_action and exit_action.action == "FULL_EXIT":
                to_close.append((symbol, price, exit_action.reason))
            elif exit_action and exit_action.action == "PARTIAL_EXIT":
                partial_qty = max(int(pos.shares * exit_action.partial_pct), 1)
                pnl = self._calc_pnl(pos, price, partial_qty)
                self.equity += pnl
                pos.shares -= partial_qty
                pos.position_size = pos.shares
                pos.partial_taken = True
            elif exit_action and exit_action.action == "ADJUST_STOP":
                if exit_action.new_stop is not None:
                    pos.stop_loss = exit_action.new_stop
                    if exit_action.reason == "BREAKEVEN":
                        pos.breakeven_triggered = True

        for symbol, price, reason in to_close:
            self._close_position(symbol, price, bar_idx, reason)

    def _process_pyramids(self, market_data, bar_idx, all_dates):
        """Check pyramid opportunities for open positions."""
        pyramid_orders = []

        for symbol, pos in list(self.positions.items()):
            if symbol not in market_data:
                continue

            df = market_data[symbol]
            date = all_dates[bar_idx]
            if date not in df.index:
                continue

            loc = df.index.get_loc(date)
            data_slice = df.iloc[:loc + 1]
            regime = detect_regime(data_slice["close"], data_slice["high"], data_slice["low"])

            pyramid = check_pyramid_opportunity(pos, data_slice, regime, self.equity)
            if pyramid:
                pyramid_orders.append((symbol, pyramid))

        for symbol, pyramid in pyramid_orders:
            pos = self.positions[symbol]
            pos.shares += pyramid.add_size
            pos.position_size = pos.shares
            pos.stop_loss = pyramid.new_stop
            pos.pyramids_added = pyramid.pyramid_level

    def _scan_entries(self, market_data, bar_idx, all_dates, dd_mult, macro_mult, macro_long_allowed):
        """Scan all symbols for new entry signals."""
        for symbol, df in market_data.items():
            if symbol in self.positions:
                continue
            if len(self.positions) >= self.max_positions:
                break

            date = all_dates[bar_idx]
            if date not in df.index:
                continue

            loc = df.index.get_loc(date)
            if loc < cfg.VOL_LOOKBACK:
                continue

            data_slice = df.iloc[:loc + 1]
            regime = detect_regime(data_slice["close"], data_slice["high"], data_slice["low"])

            signal = generate_signal(symbol, regime, data_slice)
            if signal is None or signal.direction == "NONE":
                continue

            # SPY macro filter
            if signal.direction == "LONG" and not macro_long_allowed:
                continue

            # Position sizing
            size = calculate_position_size(
                equity=self.equity,
                entry_price=signal.entry_price,
                stop_distance=signal.stop_distance,
                regime=regime,
                confluence_score=signal.confluence_score,
                has_vcp=signal.has_vcp,
                atr_percentile=signal.atr_percentile,
                drawdown_multiplier=dd_mult * macro_mult,
            )

            # Check if we can afford it
            cost = size * signal.entry_price
            if cost > self.equity * 0.2:  # Max 20% of equity in single position
                continue

            # Open position
            self.positions[symbol] = BacktestPosition(
                symbol=symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                initial_risk=signal.stop_distance,
                shares=size,
                entry_bar=bar_idx,
                regime_at_entry=regime,
                strategy_type=signal.strategy_type,
                confluence_score=signal.confluence_score,
            )

    def _close_position(self, symbol: str, exit_price: float, bar_idx: int, reason: str):
        """Close a position and record the trade."""
        if symbol not in self.positions:
            return

        pos = self.positions.pop(symbol)
        pnl = self._calc_pnl(pos, exit_price, pos.shares)
        self.equity += pnl

        r_mult = 0.0
        if pos.initial_risk > 0:
            if pos.direction == "LONG":
                r_mult = (exit_price - pos.entry_price) / pos.initial_risk
            else:
                r_mult = (pos.entry_price - exit_price) / pos.initial_risk

        self.results.trades.append(BacktestTrade(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_bar=pos.entry_bar,
            exit_bar=bar_idx,
            shares=pos.shares,
            pnl=pnl,
            pnl_pct=pnl / self.initial_equity * 100,
            r_multiple=r_mult,
            exit_reason=reason,
            regime_at_entry=pos.regime_at_entry,
            strategy_type=pos.strategy_type,
        ))

    def _close_all(self, market_data, bar_idx, all_dates, reason):
        """Close all open positions."""
        for symbol in list(self.positions.keys()):
            if symbol in market_data:
                df = market_data[symbol]
                date = all_dates[min(bar_idx, len(all_dates) - 1)]
                if date in df.index:
                    loc = df.index.get_loc(date)
                    price = float(df["close"].iloc[loc])
                    self._close_position(symbol, price, bar_idx, reason)

    @staticmethod
    def _calc_pnl(pos: BacktestPosition, exit_price: float, shares: int) -> float:
        """Calculate P&L for closing shares at exit_price."""
        if pos.direction == "LONG":
            return (exit_price - pos.entry_price) * shares
        else:
            return (pos.entry_price - exit_price) * shares
