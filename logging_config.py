"""Centralised logging configuration for the Alpaca Paper Trading Bot.

Log files (written to the ``logs/`` directory next to this file)
-----------------------------------------------------------------
app.log
    All INFO-and-above events from every module.
    Rotating: 10 MB per file, 10 backup copies (~100 MB total cap).

errors.log
    WARNING-and-above events only.
    Quick alert file — scan this first when something goes wrong.
    Rotating: 5 MB per file, 5 copies.

trades.log
    Everything emitted by the ``trades`` logger (named sub-logger).
    Daily rotation (midnight), 90-day retention — permanent audit trail.
    Write to this logger from broker/order-submission code:
        logging.getLogger("trades").info("BUY 10x AAPL @ $195.00")

risk.log
    Everything emitted by the ``risk`` logger.
    Captures all position-size calculations and circuit-breaker events.
    Rotating: 5 MB per file, 10 copies.

scanner.log
    Everything emitted by the ``scanner`` logger.
    One entry per scan run with full recommendation list.
    Rotating: 5 MB per file, 5 copies.

Console
    INFO-and-above, coloured by level when the terminal supports it.
    Can be suppressed by passing ``console=False``.

Usage
-----
    from logging_config import setup_logging
    setup_logging()            # defaults: INFO, console on, logs/ dir
    setup_logging(level=logging.DEBUG, console=False, log_dir="my_logs")
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# ANSI colour support for the console handler
# ─────────────────────────────────────────────────────────────────────────────

_LEVEL_COLOURS = {
    logging.DEBUG:    "\033[90m",    # Dark grey
    logging.INFO:     "\033[0m",     # Default (white)
    logging.WARNING:  "\033[33m",    # Yellow
    logging.ERROR:    "\033[31m",    # Red
    logging.CRITICAL: "\033[1;31m",  # Bold red
}
_RESET = "\033[0m"


class _ColouredFormatter(logging.Formatter):
    """Formatter that prepends ANSI colour codes on colour-capable terminals."""

    def __init__(self, fmt: str, datefmt: str, use_colour: bool):
        super().__init__(fmt, datefmt=datefmt)
        self._use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if self._use_colour:
            colour = _LEVEL_COLOURS.get(record.levelno, "")
            return f"{colour}{msg}{_RESET}"
        return msg


def _supports_colour(stream) -> bool:
    """Return True if *stream* looks like a colour-capable terminal."""
    try:
        return hasattr(stream, "isatty") and stream.isatty()
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main setup function
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(
    log_dir: str = os.getenv("LOG_DIR", "logs"),
    level: int = logging.INFO,
    console: bool = True,
) -> logging.Logger:
    """Configure the root logger and all named sub-loggers.

    Parameters
    ----------
    log_dir:
        Directory for log files (created if absent).
    level:
        Minimum severity for the console and app.log handlers.
    console:
        Whether to attach a coloured StreamHandler to stderr.

    Returns
    -------
    logging.Logger
        The root logger (already configured).
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # Let handlers filter individually

    # Shared format
    fmt = "%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)-22s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    file_formatter = logging.Formatter(fmt, datefmt=datefmt)

    # ── app.log — all INFO+ events ────────────────────────────────────
    _add_rotating(
        root, log_path / "app.log", level,
        file_formatter, max_bytes=10 * 1024 * 1024, backup_count=10,
    )

    # ── errors.log — WARNING+ only ───────────────────────────────────
    _add_rotating(
        root, log_path / "errors.log", logging.WARNING,
        file_formatter, max_bytes=5 * 1024 * 1024, backup_count=5,
    )

    # ── trades.log — daily rotating, permanent audit trail ───────────
    trades_logger = _isolated_logger("trades", log_path / "trades.log", logging.DEBUG, file_formatter, daily=True, backup_count=90)
    trades_logger.info("Logging initialised — trades logger ready")

    # ── risk.log — all risk decisions ─────────────────────────────────
    _isolated_logger("risk", log_path / "risk.log", logging.DEBUG, file_formatter, max_bytes=5 * 1024 * 1024, backup_count=10)

    # ── scanner.log — scan results ────────────────────────────────────
    _isolated_logger("strategies.scanner", log_path / "scanner.log", logging.DEBUG, file_formatter, max_bytes=5 * 1024 * 1024, backup_count=5)

    # ── Console ───────────────────────────────────────────────────────
    if console:
        use_colour = _supports_colour(sys.stderr)
        con_fmt = _ColouredFormatter(fmt, datefmt=datefmt, use_colour=use_colour)
        con_handler = logging.StreamHandler(sys.stderr)
        con_handler.setLevel(level)
        con_handler.setFormatter(con_fmt)
        root.addHandler(con_handler)

    root.info(
        "Logging initialised — log_dir=%s level=%s",
        log_path.resolve(), logging.getLevelName(level),
    )
    return root


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _add_rotating(
    logger: logging.Logger,
    path: Path,
    level: int,
    formatter: logging.Formatter,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 10,
) -> logging.handlers.RotatingFileHandler:
    """Attach a RotatingFileHandler to *logger*."""
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return handler


def _isolated_logger(
    name: str,
    path: Path,
    level: int,
    formatter: logging.Formatter,
    daily: bool = False,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 10,
) -> logging.Logger:
    """Create a named logger with its own file handler and propagate=False.

    Using propagate=False prevents these events from also appearing in app.log,
    keeping each file focused on its domain.
    """
    named = logging.getLogger(name)
    named.setLevel(logging.DEBUG)
    named.propagate = False   # Do NOT bubble up to root

    if daily:
        handler = logging.handlers.TimedRotatingFileHandler(
            path, when="midnight", backupCount=backup_count, encoding="utf-8",
        )
    else:
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
        )

    handler.setLevel(level)
    handler.setFormatter(formatter)
    named.addHandler(handler)
    return named


# ─────────────────────────────────────────────────────────────────────────────
# Named logger helpers (import and use anywhere)
# ─────────────────────────────────────────────────────────────────────────────

def get_trades_logger() -> logging.Logger:
    """Return the dedicated trades audit logger."""
    return logging.getLogger("trades")


def get_risk_logger() -> logging.Logger:
    """Return the dedicated risk-management logger."""
    return logging.getLogger("risk")
