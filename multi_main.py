"""Multi-account paper trading orchestrator.

Usage:
    python multi_main.py                  # Start all accounts
    python multi_main.py --dashboard      # Show performance leaderboard
    python multi_main.py --promote        # Show promotion report
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)-22s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Multi-Account Trading Bot Orchestrator")
    parser.add_argument(
        "--config", default="config/accounts.yaml",
        help="Path to accounts YAML config (default: config/accounts.yaml)",
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Show performance leaderboard and exit",
    )
    parser.add_argument(
        "--promote", action="store_true",
        help="Show promotion report and exit",
    )
    args = parser.parse_args()

    if args.dashboard:
        from multi.dashboard import show_dashboard
        show_dashboard()
        return

    if args.promote:
        from multi.promotion import show_promotion_report
        show_promotion_report(config_path=args.config)
        return

    # Default: start all accounts
    from multi.runner import MultiAccountRunner

    logger.info("Multi-Account Trading Bot starting...")
    runner = MultiAccountRunner(config_path=args.config)

    if not runner.accounts:
        logger.error("No accounts configured in %s", args.config)
        sys.exit(1)

    logger.info("Configured %d accounts:", len(runner.accounts))
    for acct in runner.accounts:
        logger.info("  - %s (%s) [%s]", acct.id, acct.label, acct.bot_type)

    runner.start_all()
    runner.monitor()


if __name__ == "__main__":
    main()
