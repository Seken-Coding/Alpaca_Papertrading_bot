"""Alpaca Paper Trading Bot — CLI entry point.

Modes
-----
Manual (AUTO_EXECUTE=false, default)
    Runs a single scan, prints recommendations, and exits.
    Use this for signal review before enabling automation.

Automatic (AUTO_EXECUTE=true)
    Starts a daily scheduler loop that fires once per trading day at
    SCAN_TIME_ET (default 15:45 ET).  On each trigger it scans for
    signals and, if the market is open, places bracket orders through
    the full three-stage risk pipeline.

    Runs until interrupted with Ctrl+C or SIGTERM (e.g. systemctl stop).
"""

import logging
import signal
import sys
import time
from datetime import datetime, date
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


def _scan_and_execute(client: AlpacaClient, risk: RiskManager) -> None:
    """Run one full scan cycle and (if AUTO_EXECUTE) place orders."""
    # Portfolio gate
    try:
        account = client.get_account()
        positions = client.get_positions()
        equity = float(account.equity)
        buying_power = float(account.buying_power)
        risk.update_equity(equity)
    except Exception as exc:
        logger.error("Account fetch failed: %s", exc)
        return

    gate = risk.check_portfolio_limits(
        position_count=len(positions),
        equity=equity,
        buying_power=buying_power,
    )
    if not gate.allowed:
        risk_logger.warning("Portfolio gate BLOCKED scan: %s", gate.reason)
        logger.warning("Trading halted by risk manager: %s", gate.reason)
        return

    risk_logger.info("Portfolio gate PASSED")

    # Scan
    scanner = StrategyScanner(
        client=client,
        strategies=[MomentumStrategy(), MeanReversionStrategy()],
    )
    recommendations = scanner.scan()

    if not recommendations:
        logger.info("No actionable recommendations this cycle.")
        return

    logger.info("=" * 72)
    logger.info("RECOMMENDATIONS (%d)", len(recommendations))
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
        )
        summary = engine.execute(recommendations)
        logger.info("Execution complete: %s", summary)
    else:
        logger.info("AUTO_EXECUTE=false — recommendations logged only, no orders placed.")


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler loop (AUTO_EXECUTE mode)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_scan_time(scan_time_et: str) -> tuple[int, int]:
    """Parse 'HH:MM' string → (hour, minute) integers."""
    try:
        h, m = scan_time_et.strip().split(":")
        return int(h), int(m)
    except ValueError:
        logger.error("Invalid SCAN_TIME_ET=%r — expected HH:MM; defaulting to 15:45", scan_time_et)
        return 15, 45


def _write_heartbeat(now: datetime) -> None:
    """Write the current timestamp to logs/heartbeat for external monitoring.

    Systemd or a cron job can check this file to verify the bot is alive.
    Failure to write never crashes the scheduler.
    """
    try:
        Path("logs/heartbeat").write_text(now.isoformat(), encoding="utf-8")
    except Exception:
        pass


def _run_scheduler(client: AlpacaClient, risk: RiskManager) -> None:
    """Block forever, firing _scan_and_execute once per trading day at SCAN_TIME_ET.

    The loop is wrapped in two try/except layers:
      - Inner: catches any unexpected exception in a single iteration and logs it,
               then continues running (prevents a transient error from killing the bot).
      - Outer: catches KeyboardInterrupt (Ctrl+C or SIGTERM) for a clean exit.
    """
    scan_hour, scan_minute = _parse_scan_time(settings.scan_time_et)
    logger.info(
        "Scheduler started — daily scan at %02d:%02d ET (AUTO_EXECUTE=%s)",
        scan_hour, scan_minute, settings.auto_execute,
    )

    last_fired: date | None = None   # Ensures we fire at most once per calendar day

    try:
        while True:
            try:
                now = datetime.now(_ET)
                today = now.date()

                # Write heartbeat every tick so monitoring can verify the bot is alive
                _write_heartbeat(now)

                # Skip weekends (just sleep — heartbeat is already written)
                if now.weekday() < 5:   # 0=Mon … 4=Fri
                    # Fire once when we reach scan time on a new day
                    at_scan_time = (now.hour == scan_hour and now.minute == scan_minute)
                    if at_scan_time and last_fired != today:
                        last_fired = today  # Mark fired now — prevents double-trigger
                        # NYSE holiday / early-close guard — Alpaca clock is ground truth.
                        if not client.is_market_open():
                            logger.info(
                                "Scheduler: market closed at %s ET — skipping scan "
                                "(holiday or early close)",
                                now.strftime("%H:%M"),
                            )
                            risk_logger.info(
                                "Scan skipped: market closed at scan time (%s)", today
                            )
                        else:
                            logger.info(
                                "Scheduler trigger — running scan cycle (%s ET)",
                                now.strftime("%H:%M"),
                            )
                            try:
                                _scan_and_execute(client, risk)
                            except Exception as exc:
                                logger.error(
                                    "Scan cycle error: %s", exc, exc_info=True
                                )

            except KeyboardInterrupt:
                raise   # Let the outer handler catch it cleanly

            except Exception as exc:
                # Unexpected crash inside one scheduler tick.  Log it and keep running —
                # the bot will retry on the next minute tick.
                logger.error(
                    "Scheduler loop error (will retry in 60s): %s", exc, exc_info=True
                )

            time.sleep(60)   # Check once per minute

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
