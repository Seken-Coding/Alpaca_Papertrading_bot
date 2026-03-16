"""Performance tracking and metrics for multi-account strategy comparison.

Each account writes daily equity snapshots to data/{account_id}/performance.json.
Metrics (Sharpe, Sortino, drawdown, etc.) are computed from these snapshots
plus trade logs.
"""

import csv
import json
import logging
import math
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Annualization factor for daily returns
_TRADING_DAYS_PER_YEAR = 252


@dataclass
class EquitySnapshot:
    """A single day's equity snapshot."""

    date: str
    equity: float
    cash: float
    positions: int


@dataclass
class AccountPerformance:
    """Computed performance metrics for one account."""

    account_id: str
    label: str
    bot_type: str
    trading_days: int
    total_trades: int
    win_rate: float
    total_return_pct: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    avg_r_multiple: float
    expectancy: float
    current_equity: float
    current_drawdown_pct: float


class PerformanceTracker:
    """Writes and reads equity snapshots for a single account."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.perf_path = Path(ctx.get_performance_path())

    def record_snapshot(self, broker) -> None:
        """Record today's equity snapshot."""
        try:
            account = broker.get_account()
            positions = broker.get_positions()
        except Exception as exc:
            logger.error("Failed to get account data for snapshot: %s", exc)
            return

        snapshot = EquitySnapshot(
            date=date.today().isoformat(),
            equity=account["equity"],
            cash=account["cash"],
            positions=len(positions),
        )

        data = self._load_data()

        # Update or append today's snapshot
        existing_dates = {s["date"] for s in data.get("snapshots", [])}
        if snapshot.date in existing_dates:
            data["snapshots"] = [
                asdict(snapshot) if s["date"] == snapshot.date else s
                for s in data["snapshots"]
            ]
        else:
            data.setdefault("snapshots", []).append(asdict(snapshot))

        # Update metadata
        data["account_id"] = self.ctx.config.id
        data["label"] = self.ctx.config.label
        data["bot_type"] = self.ctx.config.bot_type
        if "start_date" not in data:
            data["start_date"] = snapshot.date
        if "initial_equity" not in data:
            data["initial_equity"] = snapshot.equity

        self._save_data(data)
        logger.info(
            "Performance snapshot: %s equity=$%.2f positions=%d",
            self.ctx.config.id, snapshot.equity, snapshot.positions,
        )

    def _load_data(self) -> dict:
        if self.perf_path.exists():
            try:
                return json.loads(self.perf_path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_data(self, data: dict) -> None:
        tmp = self.perf_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.perf_path)


def load_all_performance(data_root: str = "data") -> list[dict]:
    """Load performance.json from all account directories."""
    results = []
    root = Path(data_root)
    if not root.exists():
        return results

    for perf_file in sorted(root.glob("*/performance.json")):
        try:
            data = json.loads(perf_file.read_text())
            if data.get("snapshots"):
                results.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping %s: %s", perf_file, exc)

    return results


def compute_metrics(perf_data: dict, data_root: str = "data") -> AccountPerformance:
    """Compute full performance metrics from snapshots and trade logs."""
    account_id = perf_data["account_id"]
    label = perf_data.get("label", account_id)
    bot_type = perf_data.get("bot_type", "unknown")
    snapshots = perf_data.get("snapshots", [])
    initial_equity = perf_data.get("initial_equity", 0)

    # Extract equity series
    equities = [s["equity"] for s in snapshots]
    trading_days = len(equities)

    # Total return
    if initial_equity > 0 and equities:
        total_return_pct = ((equities[-1] - initial_equity) / initial_equity) * 100
    else:
        total_return_pct = 0.0

    # Annualized return
    if trading_days > 1 and initial_equity > 0:
        total_return_frac = equities[-1] / initial_equity
        annualized_return = (total_return_frac ** (_TRADING_DAYS_PER_YEAR / trading_days) - 1) * 100
    else:
        annualized_return = 0.0

    # Daily returns
    daily_returns = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

    # Sharpe ratio (annualized, assuming risk-free = 0)
    sharpe_ratio = _compute_sharpe(daily_returns)

    # Sortino ratio (downside deviation only)
    sortino_ratio = _compute_sortino(daily_returns)

    # Max drawdown
    max_drawdown_pct = _compute_max_drawdown(equities)

    # Current drawdown
    if equities:
        peak = max(equities)
        current_drawdown_pct = ((peak - equities[-1]) / peak) * 100 if peak > 0 else 0.0
    else:
        current_drawdown_pct = 0.0

    # Trade-level metrics from trade log
    trade_metrics = _compute_trade_metrics(account_id, data_root)

    return AccountPerformance(
        account_id=account_id,
        label=label,
        bot_type=bot_type,
        trading_days=trading_days,
        total_trades=trade_metrics["total_trades"],
        win_rate=trade_metrics["win_rate"],
        total_return_pct=total_return_pct,
        annualized_return=annualized_return,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        max_drawdown_pct=max_drawdown_pct,
        profit_factor=trade_metrics["profit_factor"],
        avg_r_multiple=trade_metrics["avg_r_multiple"],
        expectancy=trade_metrics["expectancy"],
        current_equity=equities[-1] if equities else 0.0,
        current_drawdown_pct=current_drawdown_pct,
    )


def _compute_sharpe(daily_returns: list[float]) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def _compute_sortino(daily_returns: list[float]) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    downside = [min(r, 0) ** 2 for r in daily_returns]
    downside_dev = math.sqrt(sum(downside) / len(downside)) if downside else 0.0
    if downside_dev == 0:
        return 0.0
    return (mean / downside_dev) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def _compute_max_drawdown(equities: list[float]) -> float:
    """Max drawdown as a positive percentage (e.g. 5.2 means -5.2%)."""
    if len(equities) < 2:
        return 0.0
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
    return max_dd * 100


def _compute_trade_metrics(account_id: str, data_root: str = "data") -> dict:
    """Compute trade-level metrics from the CSV trade log."""
    trade_log = Path(data_root) / account_id / "trade_log.csv"
    result = {
        "total_trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "avg_r_multiple": 0.0,
        "expectancy": 0.0,
    }

    if not trade_log.exists():
        return result

    try:
        with open(trade_log, "r", newline="") as f:
            reader = csv.DictReader(f)
            trades = list(reader)
    except (OSError, csv.Error):
        return result

    # Filter closed trades (those with exit_price)
    closed = [t for t in trades if t.get("exit_price") and t["exit_price"] != "None"]
    if not closed:
        result["total_trades"] = len(trades)
        return result

    result["total_trades"] = len(closed)

    # P/L and R-multiple analysis
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    r_multiples = []

    for trade in closed:
        try:
            pnl = float(trade.get("pnl_dollars", 0) or 0)
            r_mult = float(trade.get("r_multiple", 0) or 0)
        except (ValueError, TypeError):
            continue

        r_multiples.append(r_mult)

        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)

    total = len(closed)
    result["win_rate"] = (wins / total * 100) if total > 0 else 0.0
    result["profit_factor"] = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    result["avg_r_multiple"] = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0

    # Expectancy = avg_win * win_rate - avg_loss * loss_rate
    if total > 0:
        avg_win = (gross_profit / wins) if wins > 0 else 0.0
        losses = total - wins
        avg_loss = (gross_loss / losses) if losses > 0 else 0.0
        win_rate_frac = wins / total
        loss_rate_frac = losses / total
        result["expectancy"] = avg_win * win_rate_frac - avg_loss * loss_rate_frac

    return result
