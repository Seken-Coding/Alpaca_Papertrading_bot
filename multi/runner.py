"""MultiAccountRunner — orchestrates N trading accounts, each in its own process.

Each account runs in a separate multiprocessing.Process for:
- True parallelism (no GIL contention)
- Crash isolation (one account crashing doesn't affect others)
- Natural state/log isolation
"""

import logging
import multiprocessing as mp
import time

from config.accounts import AccountConfig, MultiAccountConfig, load_accounts
from multi.context import AccountContext

logger = logging.getLogger(__name__)

# Stagger between account starts to avoid API rate limits
_STAGGER_SECONDS = 30


class MultiAccountRunner:
    """Orchestrate N accounts, each in its own process."""

    def __init__(self, config_path: str = "config/accounts.yaml"):
        self.multi_config = load_accounts(config_path)
        self._processes: dict[str, mp.Process] = {}

    @property
    def accounts(self) -> list[AccountConfig]:
        return self.multi_config.accounts

    def start_all(self) -> None:
        """Spawn a process for each configured account."""
        for i, account in enumerate(self.accounts):
            logger.info(
                "Starting account '%s' (%s) — %s",
                account.id, account.label, account.bot_type,
            )
            p = mp.Process(
                target=_run_account,
                args=(account,),
                name=f"bot-{account.id}",
                daemon=True,
            )
            p.start()
            self._processes[account.id] = p

            # Stagger starts to avoid simultaneous API calls
            if i < len(self.accounts) - 1:
                logger.info("Waiting %ds before starting next account...", _STAGGER_SECONDS)
                time.sleep(_STAGGER_SECONDS)

        logger.info("All %d accounts started", len(self.accounts))

    def monitor(self) -> None:
        """Block forever, restarting crashed processes."""
        try:
            while True:
                for acct_id, proc in list(self._processes.items()):
                    if not proc.is_alive():
                        exit_code = proc.exitcode
                        if exit_code is not None and exit_code != 0:
                            logger.error(
                                "Account '%s' crashed (exit code %s) — restarting in %ds",
                                acct_id, exit_code, _STAGGER_SECONDS,
                            )
                            time.sleep(_STAGGER_SECONDS)
                            self._restart(acct_id)
                        else:
                            logger.info(
                                "Account '%s' exited cleanly (code %s)",
                                acct_id, exit_code,
                            )
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Shutting down all accounts...")
            self._stop_all()

    def _restart(self, acct_id: str) -> None:
        """Restart a single account process."""
        account = next(a for a in self.accounts if a.id == acct_id)
        p = mp.Process(
            target=_run_account,
            args=(account,),
            name=f"bot-{account.id}",
            daemon=True,
        )
        p.start()
        self._processes[acct_id] = p
        logger.info("Restarted account '%s'", acct_id)

    def _stop_all(self) -> None:
        """Terminate all running processes."""
        for acct_id, proc in self._processes.items():
            if proc.is_alive():
                logger.info("Terminating account '%s'", acct_id)
                proc.terminate()
                proc.join(timeout=10)


def _run_account(config: AccountConfig) -> None:
    """Entry point for a single account process."""
    ctx = AccountContext(config)
    account_logger = ctx.setup_logging()

    account_logger.info(
        "Account process started: %s (%s) — bot_type=%s",
        config.id, config.label, config.bot_type,
    )

    try:
        if config.bot_type == "intraday":
            _run_intraday(ctx, account_logger)
        elif config.bot_type == "cest":
            _run_cest(ctx, account_logger)
        else:
            account_logger.error("Unknown bot_type: %s", config.bot_type)
    except Exception as exc:
        account_logger.error(
            "Account '%s' fatal error: %s", config.id, exc, exc_info=True,
        )
        raise


def _run_intraday(ctx: AccountContext, account_logger: logging.Logger) -> None:
    """Run the intraday bot for this account (mirrors main.py logic)."""
    from risk.manager import RiskManager, RiskConfig
    from execution.position_monitor import PositionMonitor

    s = ctx.create_settings()
    client = ctx.create_alpaca_client()
    store = ctx.create_position_store()
    journal = ctx.create_trade_journal()

    # Connect and get initial equity
    account = client.get_account()
    equity = float(account.equity)
    account_logger.info(
        "Connected — equity: $%.2f | buying power: $%.2f",
        equity, float(account.buying_power),
    )

    risk = RiskManager(RiskConfig())
    risk.set_session_equity(equity)

    # Import and run the scheduler from main.py
    from main import _run_scheduler
    heartbeat = str(ctx.log_dir / "heartbeat")
    _run_scheduler(client, risk, cfg=s, store=store, journal=journal,
                   heartbeat_path=heartbeat)


def _run_cest(ctx: AccountContext, account_logger: logging.Logger) -> None:
    """Run the CEST bot for this account (mirrors cest_main.py logic)."""
    import signal
    import time as _time

    cest_cfg = ctx.create_cest_config()
    broker = ctx.create_alpaca_broker()
    tracker = ctx.create_trade_tracker()
    state_path = ctx.get_state_path()

    # Import the daily cycle runner
    from cest_main import run_daily_cycle

    # Run with scheduler — triggers daily
    try:
        import schedule
    except ImportError:
        account_logger.error("schedule package required. pip install schedule")
        return

    _shutdown = False

    def _signal_handler(signum, frame):
        nonlocal _shutdown
        _shutdown = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    def _cycle():
        run_daily_cycle(
            broker=broker,
            tracker=tracker,
            cest_cfg=cest_cfg,
            state_path=state_path,
        )
        # Write performance snapshot after each cycle
        try:
            from multi.performance import PerformanceTracker
            perf = PerformanceTracker(ctx)
            perf.record_snapshot(broker)
        except Exception as exc:
            account_logger.warning("Performance snapshot failed: %s", exc)

    schedule.every().day.at(cest_cfg.DAILY_RUN_TIME).do(_cycle)

    account_logger.info(
        "CEST scheduler started for '%s'. Daily run at %s ET.",
        ctx.config.id, cest_cfg.DAILY_RUN_TIME,
    )

    while not _shutdown:
        schedule.run_pending()
        _time.sleep(30)

    account_logger.info("Account '%s' shutting down", ctx.config.id)
