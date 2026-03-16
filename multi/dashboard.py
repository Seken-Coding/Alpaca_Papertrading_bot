"""CLI leaderboard dashboard for multi-account strategy comparison.

Usage:
    python -m multi.dashboard
    python multi_main.py --dashboard
"""

import logging
from datetime import date

from multi.performance import load_all_performance, compute_metrics, AccountPerformance

logger = logging.getLogger(__name__)


def _format_pct(val: float) -> str:
    """Format a percentage value with sign."""
    if val >= 0:
        return f"+{val:.1f}%"
    return f"{val:.1f}%"


def _format_ratio(val: float) -> str:
    """Format a ratio to 2 decimal places."""
    return f"{val:.2f}"


def _format_pf(val: float) -> str:
    """Format profit factor."""
    if val == float("inf"):
        return "inf"
    return f"{val:.1f}"


def show_dashboard(data_root: str = "data") -> None:
    """Load all account data and display a formatted leaderboard."""
    all_data = load_all_performance(data_root)

    if not all_data:
        print("\nNo performance data found.")
        print("Run multi_main.py to start collecting data, or ensure")
        print(f"data/*/performance.json files exist under '{data_root}/'.\n")
        return

    # Compute metrics for all accounts
    metrics: list[AccountPerformance] = []
    for data in all_data:
        try:
            m = compute_metrics(data, data_root)
            metrics.append(m)
        except Exception as exc:
            logger.warning("Failed to compute metrics for %s: %s", data.get("account_id"), exc)

    if not metrics:
        print("\nCould not compute metrics for any accounts.\n")
        return

    # Sort by total return (descending)
    metrics.sort(key=lambda m: m.total_return_pct, reverse=True)

    # Find max trading days for header
    max_days = max(m.trading_days for m in metrics)

    # Print header
    width = 88
    print()
    print("=" * width)
    print(f"{'MULTI-ACCOUNT STRATEGY LEADERBOARD':^{width}}")
    print(f"{'As of ' + date.today().isoformat() + f' ({max_days} trading days)':^{width}}")
    print("=" * width)
    print()

    # Table header
    header = (
        f" {'Rank':<5} {'Account':<26} {'Return':>8} {'Sharpe':>7} "
        f"{'MaxDD':>7} {'WinRate':>8} {'PF':>5} {'Trades':>7}"
    )
    print(header)
    print(f" {'─' * 5} {'─' * 26} {'─' * 8} {'─' * 7} {'─' * 7} {'─' * 8} {'─' * 5} {'─' * 7}")

    for i, m in enumerate(metrics, 1):
        row = (
            f" {i:<5} {m.label:<26} "
            f"{_format_pct(m.total_return_pct):>8} "
            f"{_format_ratio(m.sharpe_ratio):>7} "
            f"{_format_pct(-m.max_drawdown_pct):>7} "
            f"{m.win_rate:>7.0f}% "
            f"{_format_pf(m.profit_factor):>5} "
            f"{m.total_trades:>7}"
        )
        print(row)

    # Additional details
    print()
    print(f" {'─' * width}")
    print(f" {'Account Details':}")
    print(f" {'─' * width}")
    for m in metrics:
        print(
            f"   {m.label}: equity=${m.current_equity:,.2f} | "
            f"drawdown={_format_pct(-m.current_drawdown_pct)} | "
            f"sortino={_format_ratio(m.sortino_ratio)} | "
            f"avg_R={_format_ratio(m.avg_r_multiple)} | "
            f"type={m.bot_type}"
        )

    print()
    print("=" * width)
    print()


if __name__ == "__main__":
    show_dashboard()
