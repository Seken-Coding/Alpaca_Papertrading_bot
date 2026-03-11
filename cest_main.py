"""CEST Trading Bot — Main Loop.

Composite Edge Systematic Trader.
Runs on daily bars. Designed to execute once per day after market close
(or near close) to calculate signals for the next day's open.

Scheduling: Use cron job or APScheduler to trigger at 3:55 PM ET.

Usage:
    python cest_main.py              # Run a single daily cycle
    python cest_main.py --schedule   # Run with scheduler (auto-trigger daily)
"""

import argparse
import logging
import logging.handlers
import signal
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from config import cest_settings as cfg
from config.universe import scan_universe
from strategies.regime import detect_regime, REGIME_TREND_ACTIVE, REGIME_MR_ACTIVE
from strategies.entries import generate_signal
from strategies.exits import manage_exits
from risk.position_sizing import calculate_position_size
from risk.cest_risk_manager import (
    get_drawdown_multiplier,
    passes_equity_curve_filter,
    passes_portfolio_filter,
)
from risk.gap_protection import check_position_gap_risk, check_portfolio_gap_risk
from strategies.spy_macro import detect_spy_macro
from strategies.pyramiding import check_pyramid_opportunity
from utils.trade_tracker import TradeRecord, TradeTracker
from utils.state import BotState, load_state, save_state, should_scan_universe

logger = logging.getLogger("cest")

# Graceful shutdown flag
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info("Shutdown signal received (%s)", signal.Signals(signum).name)


def setup_logging():
    """Configure CEST-specific logging."""
    from pathlib import Path

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # File handler for CEST bot
    fh = logging.handlers.RotatingFileHandler(
        cfg.LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=10,
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] %(name)-25s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] %(name)-20s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Configure root logger for CEST modules
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)


def get_broker():
    """Create and return the configured broker instance."""
    if cfg.BROKER == "alpaca":
        from broker.alpaca_broker import AlpacaBroker
        return AlpacaBroker()
    elif cfg.BROKER == "ib":
        from broker.ib_broker import IBBroker
        return IBBroker()
    else:
        raise ValueError(f"Unknown broker: {cfg.BROKER}")


def fetch_all_bars(broker, universe: list[str], timeframe: str = "1Day", limit: int = 252) -> dict:
    """Fetch daily bars for the entire universe.

    Returns
    -------
    dict : symbol -> pd.DataFrame (OHLCV)
    """
    market_data = {}
    failed = []

    for symbol in universe:
        try:
            bars = broker.get_bars(symbol, timeframe, limit)
            if not bars.empty and len(bars) >= 50:  # Need minimum data
                market_data[symbol] = bars
            else:
                failed.append(symbol)
        except Exception as e:
            logger.warning("Failed to fetch bars for %s: %s", symbol, e)
            failed.append(symbol)

    if failed:
        logger.warning("Failed to fetch data for %d symbols: %s", len(failed), failed[:10])

    logger.info("Fetched bars for %d/%d symbols", len(market_data), len(universe))
    return market_data


def close_all_positions(broker, tracker: TradeTracker) -> None:
    """Emergency close all positions (drawdown halt)."""
    logger.critical("CLOSING ALL POSITIONS — drawdown halt triggered")
    positions = broker.get_positions()

    for pos in positions:
        symbol = pos["symbol"]
        try:
            side = "sell" if pos["side"] == "LONG" else "buy"
            broker.submit_order(
                symbol=symbol,
                qty=abs(pos["qty"]),
                side=side,
                order_type="market",
            )
            tracker.record_exit(symbol, pos["current_price"], "DRAWDOWN_HALT")
            logger.info("Emergency close: %s %d shares at market", symbol, pos["qty"])
        except Exception as e:
            logger.error("Failed to emergency close %s: %s", symbol, e)


def execute_entry(broker, signal, size: int, regime: str, tracker: TradeTracker) -> bool:
    """Execute an entry order and record the trade.

    Returns True if order was successfully submitted.
    """
    # Check if shorting is allowed for this symbol
    if signal.direction == "SHORT":
        asset_info = broker.get_asset(signal.symbol) if hasattr(broker, "get_asset") else None
        if asset_info and not asset_info.get("shortable", False):
            logger.info("Skipping SHORT %s — not shortable", signal.symbol)
            return False

    side = "buy" if signal.direction == "LONG" else "sell"

    try:
        order = broker.submit_order(
            symbol=signal.symbol,
            qty=size,
            side=side,
            order_type="market",
        )

        # Record trade
        trade = TradeRecord(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            entry_date=datetime.now(),
            stop_loss=signal.stop_loss,
            initial_risk=signal.stop_distance,
            position_size=size,
            regime_at_entry=regime,
            strategy_type=signal.strategy_type,
            confluence_score=signal.confluence_score,
        )
        tracker.record_entry(trade)

        logger.info(
            "ENTRY %s %s | Regime=%s | Confluence=%d/%s | Shares=%d | "
            "Entry=$%.2f | Stop=$%.2f | Risk=%.1f%%",
            signal.direction, signal.symbol, regime,
            signal.confluence_score,
            "6" if signal.strategy_type == "TREND" else "5",
            size, signal.entry_price, signal.stop_loss,
            cfg.RISK_PER_TRADE * 100,
        )
        return True

    except Exception as e:
        logger.error("Failed to execute entry for %s: %s", signal.symbol, e)
        return False


def process_exits(broker, tracker: TradeTracker, market_data: dict) -> None:
    """Manage exits for all open positions."""
    open_trades = tracker.get_all_open_trades()

    for symbol, trade in open_trades.items():
        if symbol not in market_data:
            continue

        data = market_data[symbol]
        close = data["close"]
        high = data["high"]
        low = data["low"]

        # Update bar count
        trade.update_bar(close.iloc[-1])

        # Detect current regime
        regime = detect_regime(close, high, low)

        # Check exit conditions
        exit_action = manage_exits(trade, data, regime)

        if exit_action is None:
            continue

        if exit_action.action == "FULL_EXIT":
            # Close full position
            side = "sell" if trade.direction == "LONG" else "buy"
            try:
                broker.submit_order(
                    symbol=symbol,
                    qty=trade.position_size,
                    side=side,
                    order_type="market",
                )
                tracker.record_exit(symbol, exit_action.exit_price, exit_action.reason)
            except Exception as e:
                logger.error("Failed to exit %s: %s", symbol, e)

        elif exit_action.action == "PARTIAL_EXIT":
            # Close partial position (50%)
            partial_qty = max(int(trade.position_size * exit_action.partial_pct), 1)
            side = "sell" if trade.direction == "LONG" else "buy"
            try:
                broker.submit_order(
                    symbol=symbol,
                    qty=partial_qty,
                    side=side,
                    order_type="market",
                )
                trade.partial_taken = True
                trade.position_size -= partial_qty
                logger.info(
                    "PARTIAL EXIT %s: %d shares at $%.2f | Reason=%s",
                    symbol, partial_qty, exit_action.exit_price, exit_action.reason,
                )
            except Exception as e:
                logger.error("Failed partial exit %s: %s", symbol, e)

        elif exit_action.action == "ADJUST_STOP":
            if exit_action.new_stop is not None:
                old_stop = trade.stop_loss
                trade.stop_loss = exit_action.new_stop
                if exit_action.reason == "BREAKEVEN":
                    trade.breakeven_triggered = True
                logger.info(
                    "STOP adjusted %s: %.2f → %.2f | Reason=%s",
                    symbol, old_stop, exit_action.new_stop, exit_action.reason,
                )


def _process_pyramids(broker, tracker: TradeTracker, market_data: dict, equity: float) -> None:
    """Check pyramid (add-to-winners) opportunities for open positions."""
    open_trades = tracker.get_all_open_trades()

    for symbol, trade in open_trades.items():
        if symbol not in market_data:
            continue

        data = market_data[symbol]
        close = data["close"]
        high = data["high"]
        low = data["low"]

        regime = detect_regime(close, high, low)
        pyramid = check_pyramid_opportunity(trade, data, regime, equity)

        if pyramid is None:
            continue

        # Execute pyramid entry
        side = "buy" if pyramid.direction == "LONG" else "sell"
        try:
            broker.submit_order(
                symbol=symbol,
                qty=pyramid.add_size,
                side=side,
                order_type="market",
            )
            trade.position_size += pyramid.add_size
            trade.stop_loss = pyramid.new_stop
            trade.pyramids_added = pyramid.pyramid_level
            logger.info(
                "PYRAMID %s %s L%d | +%d shares | New stop=%.2f | %s",
                pyramid.direction, symbol, pyramid.pyramid_level,
                pyramid.add_size, pyramid.new_stop, pyramid.reason,
            )
        except Exception as e:
            logger.error("Failed pyramid entry for %s: %s", symbol, e)


def run_daily_cycle():
    """Execute one daily cycle of the CEST strategy."""
    logger.info("=" * 60)
    logger.info("CEST Daily Cycle starting at %s", datetime.now().isoformat())
    logger.info("=" * 60)

    # 1. Load state
    state = load_state()
    broker = get_broker()
    tracker = TradeTracker()

    # 2. Check if trading is halted
    if state.is_halted():
        logger.info("Trading halted until %s", state.trading_halted_until)
        return

    # 3. Weekly universe scan (if Monday or stale)
    if should_scan_universe(state):
        try:
            universe = scan_universe(broker)
            state.universe = universe
            state.last_universe_scan = datetime.now().date().isoformat()
        except Exception as e:
            logger.error("Universe scan failed: %s", e)
            if not state.universe:
                state.universe = list(cfg.CORE_ETFS)

    # Ensure we have a universe
    if not state.universe:
        state.universe = list(cfg.CORE_ETFS)
        logger.info("Using core ETFs as default universe")

    # 4. Fetch daily bars for entire universe
    market_data = fetch_all_bars(broker, state.universe)

    # 5. Update account state
    try:
        account = broker.get_account()
        state.update_equity(account["equity"])
        logger.info(
            "Account: equity=$%.2f, cash=$%.2f, buying_power=$%.2f, drawdown=%.1f%%",
            account["equity"], account["cash"], account["buying_power"],
            state.current_drawdown_pct,
        )
    except Exception as e:
        logger.error("Failed to get account info: %s", e)
        save_state(state)
        return

    # 6. Get drawdown multiplier
    dd_mult = get_drawdown_multiplier(account["equity"], state.peak_equity)
    if dd_mult == 0:
        close_all_positions(broker, tracker)
        state.halt_trading()
        save_state(state)
        return

    # 7. SPY macro regime check (Paul Tudor Jones)
    macro_mult = 1.0
    macro_long_allowed = True
    macro_short_allowed = True
    if cfg.SPY_MACRO_ENABLED and "SPY" in market_data:
        macro = detect_spy_macro(market_data["SPY"]["close"])
        macro_mult = macro.size_multiplier
        macro_long_allowed = macro.long_allowed
        macro_short_allowed = macro.short_allowed
        logger.info(
            "SPY Macro regime: %s | Longs=%s Shorts=%s | Size mult=%.2f",
            macro.regime,
            "YES" if macro_long_allowed else "NO",
            "YES" if macro_short_allowed else "NO",
            macro_mult,
        )

    # 8. Portfolio gap risk check at open
    if cfg.GAP_PROTECTION_ENABLED:
        positions_for_gap = broker.get_positions()
        gap_emergency, gap_loss = check_portfolio_gap_risk(
            account["equity"], positions_for_gap,
        )
        if gap_emergency:
            logger.critical(
                "Portfolio gap loss %.1f%% — reducing all new entries by 50%%",
                gap_loss,
            )
            macro_mult *= 0.5

    # 9. Manage existing positions FIRST
    process_exits(broker, tracker, market_data)

    # 9b. Check pyramid opportunities for open positions (Jesse Livermore)
    if cfg.PYRAMIDING_ENABLED:
        _process_pyramids(broker, tracker, market_data, account["equity"])

    # 10. Check equity curve filter
    eq_filter = passes_equity_curve_filter(tracker.get_trade_results())
    if not eq_filter:
        logger.warning("Equity curve filter active — reducing position sizes by 50%%")

    # 11. Scan for new entries
    positions = broker.get_positions()
    open_position_symbols = [p["symbol"] for p in positions]
    price_data = {sym: df["close"] for sym, df in market_data.items()}

    entries_placed = 0
    entries_blocked = 0

    for symbol in state.universe:
        if symbol in open_position_symbols:
            continue

        # Portfolio filter
        open_pos_list = [
            {"symbol": p["symbol"], "side": p["side"]}
            for p in positions
        ]
        data = market_data.get(symbol)
        if data is None or len(data) < cfg.VOL_LOOKBACK:
            continue

        regime = detect_regime(data["close"], data["high"], data["low"])

        # Generate signal
        signal = generate_signal(symbol, regime, data)
        if signal is None or signal.direction == "NONE":
            continue

        # SPY macro filter: block longs in bear markets, shorts in bull markets
        if signal.direction == "LONG" and not macro_long_allowed:
            logger.debug("SPY macro blocked LONG %s — bear market", symbol)
            entries_blocked += 1
            continue
        if signal.direction == "SHORT" and not macro_short_allowed:
            logger.debug("SPY macro blocked SHORT %s — bull market", symbol)
            entries_blocked += 1
            continue

        # Check portfolio constraints
        passes, reason = passes_portfolio_filter(
            symbol, signal.direction, open_pos_list, price_data,
        )
        if not passes:
            logger.debug("Entry blocked %s: %s", symbol, reason)
            entries_blocked += 1
            continue

        # Calculate position size
        size_mult = dd_mult * macro_mult * (0.5 if not eq_filter else 1.0)
        size = calculate_position_size(
            equity=account["equity"],
            entry_price=signal.entry_price,
            stop_distance=signal.stop_distance,
            regime=regime,
            confluence_score=signal.confluence_score,
            has_vcp=signal.has_vcp,
            atr_percentile=signal.atr_percentile,
            drawdown_multiplier=size_mult,
        )

        # Execute entry
        if execute_entry(broker, signal, size, regime, tracker):
            entries_placed += 1
            # Refresh positions list
            positions = broker.get_positions()
            open_position_symbols = [p["symbol"] for p in positions]

    # 10. Save state
    state.total_trades = tracker.total_trades
    save_state(state)

    logger.info(
        "Daily cycle complete. Open positions: %d | New entries: %d | Blocked: %d",
        len(positions), entries_placed, entries_blocked,
    )


def run_scheduled():
    """Run with a scheduler — triggers daily at configured time."""
    try:
        import schedule
    except ImportError:
        logger.error("schedule package required for --schedule mode. pip install schedule")
        sys.exit(1)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    schedule.every().day.at(cfg.DAILY_RUN_TIME).do(run_daily_cycle)

    logger.info(
        "CEST Bot scheduler started. Daily run at %s ET. Waiting...",
        cfg.DAILY_RUN_TIME,
    )

    while not _shutdown:
        schedule.run_pending()
        time.sleep(30)

    logger.info("CEST Bot shutting down gracefully")


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="CEST Trading Bot")
    parser.add_argument(
        "--schedule", action="store_true",
        help="Run with scheduler (triggers daily at configured time)",
    )
    parser.add_argument(
        "--once", action="store_true", default=True,
        help="Run a single daily cycle (default)",
    )
    args = parser.parse_args()

    logger.info("CEST Trading Bot v1.0 starting — Broker: %s, Paper: %s", cfg.BROKER, cfg.PAPER_TRADING)

    if args.schedule:
        run_scheduled()
    else:
        run_daily_cycle()


if __name__ == "__main__":
    main()
