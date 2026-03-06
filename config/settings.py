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

        # How often to scan while the market is open (in minutes).
        # Default = 5 minutes.  The bot scans repeatedly throughout the
        # trading day, not just once.
        self.scan_interval_min: int = int(os.getenv("SCAN_INTERVAL_MIN", "5"))

        # Maximum bracket orders the engine may place in a single scan run.
        self.max_orders_per_scan: int = int(os.getenv("MAX_ORDERS_PER_SCAN", "5"))

        # ── Position monitor ────────────────────────────────────────
        self.position_monitor: bool = (
            os.getenv("POSITION_MONITOR", "true").lower() == "true"
        )
        self.trailing_stop_pct: float = float(
            os.getenv("TRAILING_STOP_PCT", "1.0")
        )
        self.max_hold_days: int = int(os.getenv("MAX_HOLD_DAYS", "5"))

        # ── Market regime filter ────────────────────────────────────
        self.regime_filter: bool = (
            os.getenv("REGIME_FILTER", "false").lower() == "true"
        )

        # ── Scan time window (HH:MM in US/Eastern) ─────────────────
        self.scan_start_et: str = os.getenv("SCAN_START_ET", "10:00")
        self.scan_end_et: str = os.getenv("SCAN_END_ET", "15:30")

        # ── Universe discovery ──────────────────────────────────────
        # "static" = hardcoded SP500_SAMPLE, "dynamic" = Alpaca get_assets()
        self.universe_mode: str = os.getenv("UNIVERSE", "static").lower()
        self.universe_cache_ttl: int = int(os.getenv("UNIVERSE_CACHE_TTL", "86400"))

    @staticmethod
    def _require(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise EnvironmentError(f"Missing required environment variable: {name}")
        return value

    def __repr__(self) -> str:
        return (
            f"Settings(paper={self.paper}, auto_execute={self.auto_execute}, "
            f"scan_interval={self.scan_interval_min}m, max_orders={self.max_orders_per_scan}, "
            f"position_monitor={self.position_monitor}, trailing_stop={self.trailing_stop_pct}%, "
            f"max_hold_days={self.max_hold_days}, regime_filter={self.regime_filter}, "
            f"scan_window={self.scan_start_et}-{self.scan_end_et}, "
            f"universe={self.universe_mode})"
        )


def _get_settings() -> Settings:
    """Lazy singleton — only instantiated on first access."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

_settings: Settings | None = None

class _SettingsProxy:
    """Proxy that defers Settings() construction until first attribute access.

    This prevents import-time crashes when env vars are not set (e.g. in tests).
    """
    def __getattr__(self, name: str):
        return getattr(_get_settings(), name)

    def __repr__(self) -> str:
        return repr(_get_settings())

settings = _SettingsProxy()
