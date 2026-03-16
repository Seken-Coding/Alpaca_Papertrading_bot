"""AccountContext — isolated dependency factory for a single trading account.

Given an AccountConfig, creates all scoped objects (broker, stores, loggers)
with per-account data and log directories.
"""

import logging
import logging.handlers
from pathlib import Path

from config.accounts import AccountConfig
from config.settings import Settings
from config.cest_settings import CestConfig


class AccountContext:
    """All dependencies for a single account, fully isolated."""

    def __init__(self, config: AccountConfig):
        self.config = config
        self.data_dir = config.data_dir
        self.log_dir = config.log_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def create_alpaca_broker(self):
        """Create an AlpacaBroker with this account's credentials."""
        from broker.alpaca_broker import AlpacaBroker
        return AlpacaBroker(
            api_key=self.config.api_key,
            secret_key=self.config.secret_key,
            paper=self.config.paper,
        )

    def create_alpaca_client(self):
        """Create an AlpacaClient with this account's credentials."""
        from broker.client import AlpacaClient
        return AlpacaClient(
            api_key=self.config.api_key,
            secret_key=self.config.secret_key,
            paper=self.config.paper,
        )

    def create_position_store(self):
        """Create a PositionStore scoped to this account's data dir."""
        from execution.position_store import PositionStore
        return PositionStore(path=self.data_dir / "positions.json")

    def create_trade_journal(self):
        """Create a TradeJournal scoped to this account's data dir."""
        from execution.trade_journal import TradeJournal
        return TradeJournal(path=self.data_dir / "trade_journal.csv")

    def create_trade_tracker(self):
        """Create a TradeTracker scoped to this account's data dir."""
        from utils.trade_tracker import TradeTracker
        return TradeTracker(log_path=str(self.data_dir / "trade_log.csv"))

    def create_settings(self) -> Settings:
        """Create a Settings instance with this account's credentials and overrides."""
        return Settings.with_overrides(
            api_key=self.config.api_key,
            secret_key=self.config.secret_key,
            paper=self.config.paper,
            **self.config.strategy_overrides,
        )

    def create_cest_config(self) -> CestConfig:
        """Create a CestConfig with this account's overrides applied."""
        overrides = dict(self.config.strategy_overrides)
        # Override data paths to be account-scoped
        overrides["TRADE_LOG_PATH"] = str(self.data_dir / "trade_log.csv")
        overrides["STATE_PATH"] = str(self.data_dir / "bot_state.json")
        overrides["LOG_PATH"] = str(self.log_dir / "cest_bot.log")
        return CestConfig.from_overrides(overrides)

    def get_state_path(self) -> str:
        """Return the account-scoped bot state path."""
        return str(self.data_dir / "bot_state.json")

    def get_performance_path(self) -> str:
        """Return the account-scoped performance snapshot path."""
        return str(self.data_dir / "performance.json")

    def setup_logging(self) -> logging.Logger:
        """Configure per-account logging under this account's log directory."""
        fmt = "%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)-22s %(message)s"
        datefmt = "%Y-%m-%d %H:%M:%S"
        formatter = logging.Formatter(fmt, datefmt=datefmt)

        # Create account-specific logger
        account_logger = logging.getLogger(f"account.{self.config.id}")
        account_logger.setLevel(logging.DEBUG)

        # File handler
        fh = logging.handlers.RotatingFileHandler(
            self.log_dir / "app.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        account_logger.addHandler(fh)

        # Console handler with account prefix
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        prefix_fmt = f"%(asctime)s [{self.config.id}] [%(levelname)-8s] %(message)s"
        ch.setFormatter(logging.Formatter(prefix_fmt, datefmt=datefmt))
        account_logger.addHandler(ch)

        # Also redirect the root logger for this process to the account's log dir
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root_fh = logging.handlers.RotatingFileHandler(
            self.log_dir / "all.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        root_fh.setLevel(logging.DEBUG)
        root_fh.setFormatter(formatter)
        root.addHandler(root_fh)

        return account_logger
