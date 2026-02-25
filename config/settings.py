"""Application settings loaded from environment variables."""

import os


class Settings:
    """Loads and validates configuration from environment."""

    def __init__(self):
        # ── Broker credentials (required) ─────────────────────────────
        self.api_key: str = self._require("ALPACA_API_KEY")
        self.secret_key: str = self._require("ALPACA_SECRET_KEY")
        self.paper: bool = os.getenv("ALPACA_PAPER", "true").lower() == "true"

        # ── Automation (optional, safe defaults = manual mode) ─────────
        self.auto_execute: bool = os.getenv("AUTO_EXECUTE", "false").lower() == "true"

        # Time-of-day (US/Eastern) at which the daily scan+execute fires.
        # Format: "HH:MM" 24-hour.  Default = 15:45 (15 min before market close).
        self.scan_time_et: str = os.getenv("SCAN_TIME_ET", "15:45")

        # Maximum bracket orders the engine may place in a single scan run.
        self.max_orders_per_scan: int = int(os.getenv("MAX_ORDERS_PER_SCAN", "3"))

    @staticmethod
    def _require(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise EnvironmentError(f"Missing required environment variable: {name}")
        return value

    def __repr__(self) -> str:
        return (
            f"Settings(paper={self.paper}, auto_execute={self.auto_execute}, "
            f"scan_time_et={self.scan_time_et}, max_orders={self.max_orders_per_scan})"
        )


settings = Settings()
