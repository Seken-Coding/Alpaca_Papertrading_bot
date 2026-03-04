"""Alpaca Paper Trading Bot — CLI entry point.

Modes
-----
Manual (AUTO_EXECUTE=false, default)
    Runs a single scan, prints recommendations, and exits.
    Use this for signal review before enabling automation.

Automatic (AUTO_EXECUTE=true)
    Scans every SCAN_INTERVAL_MIN minutes (default 5) while the market
    is open.  Each scan evaluates strategies and, if signals pass the
    three-stage risk pipeline, places bracket orders.  Sleeps between
    scans and goes idle when the market is closed (evenings, weekends,
    holidays).

    Runs until interrupted with Ctrl+C or SIGTERM (e.g. systemctl stop).
"""

import logging
import signal
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from logging_config import setup_logging
from config.settings import settings
from broker.client import AlpacaClient
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.scanner import StrategyScanner
from risk.manager import RiskManager, RiskConfig
from execution.engine import ExecutionEngine
from execution.position_store import PositionStore
from execution.trade_journal import TradeJournal
from execution.position_monitor import PositionMonitor
from execution.market_regime import MarketRegimeFilter

# ── Logging ───────────────────────────────────────────────────────────────────
setup_logging()
logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")
risk_logger = logging.getLogger("risk")

_ET = ZoneInfo("America/New_York")


# ── Signal handling ───────────────────────────────────────────────────────────
# Translate SIGTERM (sent by systemd / Docker / process managers on shutdown)
# into a clean KeyboardInterrupt so the scheduler can exit gracefully.

def _handle_sigterm(signum, frame):
    logger.info("SIGTERM received — initiating clean shutdown")
    raise KeyboardInterrupt

signal.signal(signal.SIGTERM, _handle_sigterm)


# ─────────────────────────────────────────────────────────────────────────────
# Core scan-and-execute logic (shared by both modes)
# ─────────────────────────────────────────────────────────────────────────────

def _connect() -> tuple[AlpacaClient, RiskManager]:
    """Connect to Alpaca and initialise the risk manager."""
    client = AlpacaClient(
        api_key=settings.api_key,
        secret_key=settings.secret_key,
        paper=settings.paper,
    )
    try:
        account = client.get_account()
    except Exception as exc:
        logger.error("Failed to connect to Alpaca: %s", exc)
        sys.exit(1)

    equity = float(account.equity)
    buying_power = float(account.buying_power)
    logger.info(
        "Connected — status: %s | equity: $%.2f | buying power: $%.2f",
        account.status, equity, buying_power,
    )

    risk = RiskManager(RiskConfig())
    risk.set_session_equity(equity)
    return client, risk


def _scan_and_execute(
    client: AlpacaClient,
    risk: RiskManager,
    store: PositionStore | None = None,
    journal: TradeJournal | None = None,
) -> str:
    """Run one full scan cycle and (if AUTO_EXECUTE) place orders.

    Returns a short summary string for the scheduler to report in status logs.
    """
    scan_start = time.monotonic()

    # Refresh account state for risk tracking
    try:
        account = client.get_account()
        equity = float(account.equity)
        buying_power = float(account.buying_power)
        risk.update_equity(equity)
        logger.info(
            "Account state — equity: $%.2f | buying power: $%.2f",
            equity, buying_power,
        )
    except Exception as exc:
        logger.error("Account fetch failed: %s", exc)
        return f"account fetch failed: {exc}"

    # ── Market regime gate ──────────────────────────────────────────
    if settings.regime_filter:
        regime = MarketRegimeFilter(client).classify()
        if regime == "BEAR":
            logger.warning(
                "REGIME FILTER: BEAR market detected (SPY < SMA-200) — "
                "suppressing BUY signals this scan"
            )
            risk_logger.warning("Regime gate: BEAR — BUY signals suppressed")
            return "regime=BEAR — scan suppressed"
        else:
            logger.info("REGIME FILTER: %s — proceeding with scan", regime)

    # Scan (portfolio gate is checked inside ExecutionEngine.execute)
    logger.info("Starting strategy scan ...")
    scanner = StrategyScanner(
        client=client,
        strategies=[MomentumStrategy(), MeanReversionStrategy()],
        universe_mode=settings.universe_mode,
        universe_cache_ttl=settings.universe_cache_ttl,
    )
    recommendations = scanner.scan()

    scan_elapsed = time.monotonic() - scan_start
    if not recommendations:
        logger.info(
            "No actionable recommendations this cycle (scan took %.1fs).",
            scan_elapsed,
        )
        return "no actionable recommendations"

    logger.info("=" * 72)
    logger.info("RECOMMENDATIONS (%d) — scan took %.1fs", len(recommendations), scan_elapsed)
    for rec in recommendations:
        logger.info(str(rec))
        trades_logger.info("RECOMMENDATION | %s", str(rec))
    logger.info("=" * 72)

    # Auto-execute
    if settings.auto_execute:
        logger.info("AUTO_EXECUTE=true — passing to ExecutionEngine")
        engine = ExecutionEngine(
            client=client,
            risk_manager=risk,
            max_orders=settings.max_orders_per_scan,
            require_market_open=True,
            position_store=store,
            trade_journal=journal,
        )
        summary = engine.execute(recommendations)
        total_elapsed = time.monotonic() - scan_start
        logger.info("Execution complete (%.1fs total): %s", total_elapsed, summary)
        return (
            f"placed {len(summary.placed)}, blocked {len(summary.blocked)}, "
            f"skipped {len(summary.skipped)}, errors {len(summary.errors)}"
        )
    else:
        logger.info("AUTO_EXECUTE=false — recommendations logged only, no orders placed.")
        return f"{len(recommendations)} recommendations (auto-execute off)"


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler loop (AUTO_EXECUTE mode)
# ─────────────────────────────────────────────────────────────────────────────

def _write_heartbeat(now: datetime) -> None:
    """Write the current timestamp to logs/heartbeat for external monitoring.

    Systemd or a cron job can check this file to verify the bot is alive.
    Failure to write never crashes the scheduler.
    """
    try:
        Path("logs/heartbeat").write_text(now.isoformat(), encoding="utf-8")
    except Exception:
        pass


_STATUS_INTERVAL = timedelta(minutes=10)
_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _format_delta(td: timedelta) -> str:
    """Format a timedelta as 'Xh Ym'."""
    total_min = int(td.total_seconds()) // 60
    h, m = divmod(total_min, 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _parse_time(t: str):
    """Parse 'HH:MM' string into (hour, minute) tuple, or None on failure."""
    try:
        h, m = t.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return None


def _in_scan_window(now_et: datetime) -> bool:
    """Return True if current ET time is within the configured scan window."""
    start = _parse_time(settings.scan_start_et)
    end = _parse_time(settings.scan_end_et)
    if start is None or end is None:
        logger.warning("Scan window misconfigured — treating as always open")
        return True
    now_t = (now_et.hour, now_et.minute)
    return start <= now_t <= end


def _run_scheduler(client: AlpacaClient, risk: RiskManager) -> None:
    """Block forever, scanning every SCAN_INTERVAL_MIN minutes while the market is open.

    The loop checks every 60 seconds.  When the market is open and enough
    time has elapsed since the last scan, a new scan cycle runs.  When the
    market is closed (evenings, weekends, holidays) the bot idles and logs
    a status message every 10 minutes.
    """
    scan_interval = timedelta(minutes=settings.scan_interval_min)

    # Shared across ticks — created once
    _store = PositionStore()
    _journal = TradeJournal()
    _monitor = PositionMonitor(client=client, store=_store, journal=_journal)

    logger.info(
        "Scheduler started — scanning every %dm while market is open (AUTO_EXECUTE=%s)",
        settings.scan_interval_min, settings.auto_execute,
    )

    last_scan_at: datetime | None = None     # When the last scan started
    last_status_log: datetime | None = None  # Timestamp of last status message
    last_scan_result: str = ""               # One-line summary of last scan outcome
    scans_today: int = 0                     # How many scans fired today
    current_day: date | None = None          # Track day rollovers

    try:
        while True:
            try:
                now = datetime.now(_ET)
                today = now.date()

                # Reset daily counter on day change
                if current_day != today:
                    current_day = today
                    scans_today = 0
                    last_scan_result = ""

                # Write heartbeat every tick
                _write_heartbeat(now)

                # ── Check market status ────────────────────────────────────
                market_open = client.is_market_open()

                # ── Periodic status log (every 10 minutes) ────────────────
                if last_status_log is None or (now - last_status_log) >= _STATUS_INTERVAL:
                    last_status_log = now
                    day_name = _DAY_NAMES[now.weekday()]
                    time_str = now.strftime("%H:%M")

                    if now.weekday() >= 5:
                        days_to_mon = 7 - now.weekday()
                        logger.info(
                            "Status — %s ET %s — weekend, market reopens Monday (%dd)",
                            time_str, day_name, days_to_mon,
                        )
                    elif not market_open:
                        logger.info(
                            "Status — %s ET %s — market closed, scans today: %d | last: %s",
                            time_str, day_name, scans_today,
                            last_scan_result or "none yet",
                        )
                    else:
                        # Market is open
                        if last_scan_at is not None:
                            since = now - last_scan_at
                            next_in = scan_interval - since
                            next_str = (
                                f"next scan in {_format_delta(next_in)}"
                                if next_in.total_seconds() > 0
                                else "next scan imminent"
                            )
                        else:
                            next_str = "first scan imminent"
                        logger.info(
                            "Status — %s ET %s — market open, %s | scans today: %d | last: %s",
                            time_str, day_name, next_str, scans_today,
                            last_scan_result or "none yet",
                        )

                # ── Market-open actions ────────────────────────────────────
                if market_open:
                    # Position monitor runs every tick (not gated by scan window)
                    try:
                        _monitor.run()
                    except Exception as exc:
                        logger.error(
                            "Position monitor error (non-fatal): %s",
                            exc, exc_info=True,
                        )

                    # Scan window gate
                    in_window = _in_scan_window(now)
                    if not in_window:
                        logger.debug(
                            "Outside scan window %s–%s ET — skipping scan",
                            settings.scan_start_et, settings.scan_end_et,
                        )
                    else:
                        time_to_scan = (
                            last_scan_at is None
                            or (now - last_scan_at) >= scan_interval
                        )
                        if time_to_scan:
                            last_scan_at = now
                            scans_today += 1
                            logger.info(
                                "Scan #%d — running scan cycle (%s ET)",
                                scans_today, now.strftime("%H:%M"),
                            )
                            try:
                                result = _scan_and_execute(
                                    client, risk, store=_store, journal=_journal,
                                )
                                last_scan_result = result or "no actionable recommendations"
                            except Exception as exc:
                                last_scan_result = f"error: {exc}"
                                logger.error(
                                    "Scan cycle error: %s", exc, exc_info=True,
                                )

            except KeyboardInterrupt:
                raise

            except Exception as exc:
                logger.error(
                    "Scheduler loop error (will retry in 60s): %s", exc, exc_info=True,
                )

            time.sleep(60)

    except KeyboardInterrupt:
        logger.info("Scheduler stopped — exiting cleanly")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Alpaca Paper Trading Bot — %s", settings)
    client, risk = _connect()

    if settings.auto_execute:
        # Continuous mode: loop until Ctrl+C or SIGTERM
        _run_scheduler(client, risk)
    else:
        # One-shot mode: scan once and exit
        _scan_and_execute(client, risk)


if __name__ == "__main__":
    main()
