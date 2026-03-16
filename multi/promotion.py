"""Strategy promotion — rank accounts and recommend the best for live trading.

Uses composite scoring with configurable weights to rank eligible accounts.
Accounts must meet minimum trading days and trade count thresholds.

Usage:
    python multi_main.py --promote
    python -m multi.promotion
"""

import logging
from dataclasses import dataclass, field

from config.accounts import load_accounts, PromotionConfig
from multi.performance import (
    load_all_performance,
    compute_metrics,
    AccountPerformance,
)

logger = logging.getLogger(__name__)

# Hard disqualification thresholds
_MAX_DRAWDOWN_DISQUALIFY = 20.0  # percent
_MIN_SHARPE_DISQUALIFY = 0.0     # negative Sharpe = disqualified


@dataclass
class PromotionResult:
    """Result for a single account in the promotion ranking."""

    account_id: str
    label: str
    eligible: bool
    disqualified: bool
    disqualify_reason: str = ""
    composite_score: float = 0.0
    metrics: AccountPerformance = None


@dataclass
class PromotionReport:
    """Full promotion report across all accounts."""

    recommended_account_id: str | None
    results: list[PromotionResult]
    eligible_count: int
    disqualified_count: int


def generate_promotion_report(
    config_path: str = "config/accounts.yaml",
    data_root: str = "data",
) -> PromotionReport:
    """Analyze all accounts and return ranked results with recommendation."""
    multi_config = load_accounts(config_path)
    promo_cfg = multi_config.promotion

    all_data = load_all_performance(data_root)

    if not all_data:
        return PromotionReport(
            recommended_account_id=None,
            results=[],
            eligible_count=0,
            disqualified_count=0,
        )

    # Compute metrics for all accounts
    all_metrics: list[AccountPerformance] = []
    for data in all_data:
        try:
            m = compute_metrics(data, data_root)
            all_metrics.append(m)
        except Exception as exc:
            logger.warning("Skipping %s: %s", data.get("account_id"), exc)

    # Evaluate each account
    results: list[PromotionResult] = []
    for m in all_metrics:
        result = PromotionResult(
            account_id=m.account_id,
            label=m.label,
            eligible=True,
            disqualified=False,
            metrics=m,
        )

        # Check eligibility gate
        if m.trading_days < promo_cfg.min_trading_days:
            result.eligible = False
            result.disqualify_reason = (
                f"Insufficient trading days: {m.trading_days}/{promo_cfg.min_trading_days}"
            )
        elif m.total_trades < promo_cfg.min_total_trades:
            result.eligible = False
            result.disqualify_reason = (
                f"Insufficient trades: {m.total_trades}/{promo_cfg.min_total_trades}"
            )

        # Check hard disqualifiers
        if m.max_drawdown_pct > _MAX_DRAWDOWN_DISQUALIFY:
            result.disqualified = True
            result.eligible = False
            result.disqualify_reason = (
                f"Max drawdown {m.max_drawdown_pct:.1f}% exceeds {_MAX_DRAWDOWN_DISQUALIFY}% limit"
            )
        elif m.sharpe_ratio < _MIN_SHARPE_DISQUALIFY:
            result.disqualified = True
            result.eligible = False
            result.disqualify_reason = (
                f"Negative Sharpe ratio: {m.sharpe_ratio:.2f}"
            )

        results.append(result)

    # Compute composite scores for eligible accounts
    eligible = [r for r in results if r.eligible and not r.disqualified]

    if eligible:
        _compute_composite_scores(eligible, promo_cfg)

    # Sort by composite score (descending)
    results.sort(key=lambda r: r.composite_score, reverse=True)

    recommended = results[0].account_id if results and results[0].eligible else None

    return PromotionReport(
        recommended_account_id=recommended,
        results=results,
        eligible_count=len(eligible),
        disqualified_count=len([r for r in results if r.disqualified]),
    )


def _compute_composite_scores(
    eligible: list[PromotionResult],
    promo_cfg: PromotionConfig,
) -> None:
    """Compute weighted composite scores using min-max normalization."""
    weights = promo_cfg.ranking_weights

    # Collect raw metric values
    metric_values: dict[str, list[float]] = {
        "sharpe_ratio": [],
        "total_return_pct": [],
        "max_drawdown_pct": [],
        "profit_factor": [],
        "win_rate": [],
    }

    for r in eligible:
        m = r.metrics
        metric_values["sharpe_ratio"].append(m.sharpe_ratio)
        metric_values["total_return_pct"].append(m.total_return_pct)
        metric_values["max_drawdown_pct"].append(m.max_drawdown_pct)
        pf = m.profit_factor if m.profit_factor != float("inf") else 10.0
        metric_values["profit_factor"].append(pf)
        metric_values["win_rate"].append(m.win_rate)

    # Normalize each metric to 0-100 range
    normalized: dict[str, list[float]] = {}
    for metric, values in metric_values.items():
        if len(set(values)) <= 1:
            # All same value — normalize to 50
            normalized[metric] = [50.0] * len(values)
        else:
            min_val = min(values)
            max_val = max(values)
            spread = max_val - min_val
            if metric == "max_drawdown_pct":
                # Lower is better — invert
                normalized[metric] = [
                    ((max_val - v) / spread) * 100 for v in values
                ]
            else:
                normalized[metric] = [
                    ((v - min_val) / spread) * 100 for v in values
                ]

    # Compute weighted composite score
    for i, r in enumerate(eligible):
        score = 0.0
        for metric, weight in weights.items():
            if metric in normalized:
                score += normalized[metric][i] * weight
        r.composite_score = score


def show_promotion_report(
    config_path: str = "config/accounts.yaml",
    data_root: str = "data",
) -> None:
    """Display the promotion report to the console."""
    report = generate_promotion_report(config_path, data_root)

    width = 80
    print()
    print("=" * width)
    print(f"{'STRATEGY PROMOTION REPORT':^{width}}")
    print("=" * width)

    if not report.results:
        print("\nNo performance data available yet.")
        print("Run multi_main.py to start collecting trading data.\n")
        return

    print(f"\n  Accounts analyzed: {len(report.results)}")
    print(f"  Eligible:          {report.eligible_count}")
    print(f"  Disqualified:      {report.disqualified_count}")

    # Show rankings
    print(f"\n  {'─' * (width - 4)}")
    print(f"  {'Rank':<5} {'Account':<26} {'Score':>8} {'Status':<20}")
    print(f"  {'─' * 5} {'─' * 26} {'─' * 8} {'─' * 20}")

    for i, r in enumerate(report.results, 1):
        if r.eligible and not r.disqualified:
            status = "ELIGIBLE"
            if r.account_id == report.recommended_account_id:
                status = "RECOMMENDED"
        elif r.disqualified:
            status = "DISQUALIFIED"
        else:
            status = "NOT ELIGIBLE"

        print(f"  {i:<5} {r.label:<26} {r.composite_score:>7.1f} {status:<20}")

        if r.disqualify_reason:
            print(f"        {r.disqualify_reason}")

    # Show details for recommended account
    if report.recommended_account_id:
        rec = next(r for r in report.results if r.account_id == report.recommended_account_id)
        m = rec.metrics
        print(f"\n  {'─' * (width - 4)}")
        print(f"  RECOMMENDED: {rec.label}")
        print(f"  {'─' * (width - 4)}")
        print(f"    Total Return:    {m.total_return_pct:+.1f}%")
        print(f"    Sharpe Ratio:    {m.sharpe_ratio:.2f}")
        print(f"    Max Drawdown:    {m.max_drawdown_pct:.1f}%")
        print(f"    Win Rate:        {m.win_rate:.0f}%")
        print(f"    Profit Factor:   {m.profit_factor:.2f}")
        print(f"    Total Trades:    {m.total_trades}")
        print(f"    Trading Days:    {m.trading_days}")
        print(f"    Current Equity:  ${m.current_equity:,.2f}")
    else:
        print(f"\n  No account meets promotion criteria yet.")

    print()
    print("=" * width)
    print()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    show_promotion_report()
