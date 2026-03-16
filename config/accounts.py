"""Multi-account configuration loader.

Parses config/accounts.yaml, resolves env-var references to actual API keys,
and returns typed AccountConfig instances.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AccountConfig:
    """Fully resolved configuration for a single trading account."""

    id: str
    label: str
    bot_type: str  # "intraday" or "cest"
    api_key: str
    secret_key: str
    paper: bool
    strategy_overrides: dict[str, Any]
    data_dir: Path = field(init=False)
    log_dir: Path = field(init=False)

    def __post_init__(self):
        self.data_dir = Path(f"data/{self.id}")
        self.log_dir = Path(f"logs/{self.id}")


@dataclass
class PromotionConfig:
    """Criteria for selecting the best-performing account."""

    min_trading_days: int = 30
    min_total_trades: int = 20
    ranking_weights: dict[str, float] = field(default_factory=lambda: {
        "sharpe_ratio": 0.30,
        "total_return_pct": 0.25,
        "max_drawdown_pct": 0.20,
        "profit_factor": 0.15,
        "win_rate": 0.10,
    })


@dataclass
class MultiAccountConfig:
    """Top-level multi-account configuration."""

    accounts: list[AccountConfig]
    promotion: PromotionConfig


def load_accounts(config_path: str = "config/accounts.yaml") -> MultiAccountConfig:
    """Load and validate multi-account configuration from YAML.

    API key env-var names are resolved to actual values from the environment.
    Raises EnvironmentError if referenced env vars are missing.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Account config not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    if not raw or "accounts" not in raw:
        raise ValueError(f"Invalid accounts config: missing 'accounts' key in {path}")

    accounts = []
    for entry in raw["accounts"]:
        # Resolve env vars
        api_key_env = entry["api_key_env"]
        secret_key_env = entry["secret_key_env"]

        api_key = os.getenv(api_key_env)
        secret_key = os.getenv(secret_key_env)

        if not api_key or not secret_key:
            raise EnvironmentError(
                f"Account '{entry['id']}': missing env vars "
                f"{api_key_env} and/or {secret_key_env}. "
                f"Add them to your .env file."
            )

        bot_type = entry.get("bot_type", "cest")
        if bot_type not in ("intraday", "cest"):
            raise ValueError(
                f"Account '{entry['id']}': invalid bot_type '{bot_type}' "
                f"(must be 'intraday' or 'cest')"
            )

        accounts.append(AccountConfig(
            id=entry["id"],
            label=entry.get("label", entry["id"]),
            bot_type=bot_type,
            api_key=api_key,
            secret_key=secret_key,
            paper=entry.get("paper", True),
            strategy_overrides=entry.get("strategy_overrides", {}),
        ))

    # Promotion config
    promo_raw = raw.get("promotion", {})
    _default_weights = {
        "sharpe_ratio": 0.30,
        "total_return_pct": 0.25,
        "max_drawdown_pct": 0.20,
        "profit_factor": 0.15,
        "win_rate": 0.10,
    }
    promotion = PromotionConfig(
        min_trading_days=promo_raw.get("min_trading_days", 30),
        min_total_trades=promo_raw.get("min_total_trades", 20),
        ranking_weights=promo_raw.get("ranking_weights", _default_weights),
    )

    return MultiAccountConfig(accounts=accounts, promotion=promotion)
