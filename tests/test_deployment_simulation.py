"""Deployment simulation tests.

Validates that the bot can be deployed and started successfully:
- All modules import without errors
- All dependencies are available at correct versions
- Both bot entry points (intraday + CEST) initialise components
- Deployment configs (systemd, setup script) are well-formed
- Risk pipeline components produce sane outputs
- Multi-account orchestrator loads config
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Ensure env vars are set so Settings() doesn't crash ──────────────────────
os.environ.setdefault("ALPACA_API_KEY", "test_deploy_key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_deploy_secret")
os.environ.setdefault("ALPACA_PAPER", "true")
os.environ.setdefault("AUTO_EXECUTE", "false")

ROOT = Path(__file__).resolve().parent.parent


# =============================================================================
# 1. Dependency checks
# =============================================================================


class TestDependencies:
    """Verify all required packages are importable."""

    @pytest.mark.parametrize("package", [
        "alpaca", "pandas", "numpy", "dotenv", "schedule", "yaml", "pytz",
    ])
    def test_core_dependency_importable(self, package):
        mod = importlib.import_module(package)
        assert mod is not None

    def test_requirements_file_exists(self):
        assert (ROOT / "requirements.txt").is_file()

    def test_requirements_parseable(self):
        lines = (ROOT / "requirements.txt").read_text().splitlines()
        pkg_lines = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
        assert len(pkg_lines) >= 5, "Expected at least 5 dependencies"


# =============================================================================
# 2. Module import tests
# =============================================================================


ALL_MODULES = [
    "config.settings",
    "config.cest_settings",
    "broker.base",
    "broker.client",
    "broker.alpaca_broker",
    "broker.errors",
    "strategies.momentum",
    "strategies.mean_reversion",
    "strategies.scanner",
    "strategies.screener",
    "strategies.regime",
    "strategies.entries",
    "strategies.exits",
    "strategies.patterns",
    "strategies.pyramiding",
    "strategies.spy_macro",
    "strategies.darvas_box",
    "execution.engine",
    "execution.position_store",
    "execution.trade_journal",
    "execution.position_monitor",
    "execution.market_regime",
    "analysis.indicators",
    "analysis.cest_indicators",
    "analysis.scorer",
    "analysis.signals",
    "analysis.data_loader",
    "risk.manager",
    "risk.cest_risk_manager",
    "risk.position_sizing",
    "risk.gap_protection",
    "utils.state",
    "utils.trade_tracker",
    "multi.context",
    "multi.runner",
    "multi.dashboard",
    "multi.performance",
    "multi.promotion",
    "config.universe",
    "logging_config",
]


class TestModuleImports:
    """Every bot module must import without errors."""

    @pytest.mark.parametrize("module_name", ALL_MODULES)
    def test_module_imports(self, module_name):
        mod = importlib.import_module(module_name)
        assert mod is not None


# =============================================================================
# 3. Intraday bot component initialisation
# =============================================================================


class TestIntradayBotInit:
    """Simulate intraday bot startup — everything up to the Alpaca connection."""

    def test_settings_load(self):
        from config.settings import settings
        assert settings.paper is True
        assert settings.auto_execute is False
        assert settings.scan_interval_min > 0
        assert settings.max_orders_per_scan > 0

    def test_risk_manager_init(self):
        from risk.manager import RiskManager, RiskConfig
        rc = RiskConfig()
        rm = RiskManager(rc)
        rm.set_session_equity(100_000)
        # Should not raise

    def test_strategies_instantiate(self):
        from strategies.momentum import MomentumStrategy
        from strategies.mean_reversion import MeanReversionStrategy
        ms = MomentumStrategy()
        mrs = MeanReversionStrategy()
        assert ms is not None
        assert mrs is not None

    def test_position_store_init(self):
        from execution.position_store import PositionStore
        ps = PositionStore()
        assert ps is not None

    def test_trade_journal_init(self):
        from execution.trade_journal import TradeJournal
        tj = TradeJournal()
        assert tj is not None


# =============================================================================
# 4. CEST bot component initialisation
# =============================================================================


class TestCESTBotInit:
    """Simulate CEST bot startup — everything up to the broker connection."""

    def test_cest_settings(self):
        from config import cest_settings as cfg
        assert cfg.BROKER == "alpaca"
        assert cfg.PAPER_TRADING is True
        assert cfg.RISK_PER_TRADE > 0
        assert cfg.MAX_POSITIONS > 0
        assert len(cfg.CORE_ETFS) >= 10

    def test_bot_state_lifecycle(self):
        from utils.state import BotState
        state = BotState()
        assert state.is_halted() is False
        state.update_equity(100_000)
        assert state.peak_equity == 100_000

    def test_trade_tracker_init(self):
        from utils.trade_tracker import TradeTracker
        tt = TradeTracker()
        assert tt.total_trades == 0

    def test_drawdown_multiplier(self):
        from risk.cest_risk_manager import get_drawdown_multiplier
        assert get_drawdown_multiplier(100_000, 100_000) == 1.0  # no drawdown
        assert get_drawdown_multiplier(95_000, 100_000) < 1.0    # 5% drawdown
        assert get_drawdown_multiplier(80_000, 100_000) == 0      # 20% halt

    def test_position_sizing(self):
        from risk.position_sizing import calculate_position_size
        size = calculate_position_size(
            equity=100_000,
            entry_price=50.0,
            stop_distance=2.0,
            regime="TREND_UP",
            confluence_score=5,
            has_vcp=False,
            atr_percentile=50.0,
            drawdown_multiplier=1.0,
        )
        assert size >= 1
        assert size <= 2000  # sanity upper bound for $100k equity, $50 stock

    def test_cest_config_dataclass(self):
        from config.cest_settings import CestConfig
        c = CestConfig()
        assert c.BROKER == "alpaca"
        assert c.RISK_PER_TRADE == 0.01

    def test_cest_config_from_overrides(self):
        from config.cest_settings import CestConfig
        c = CestConfig.from_overrides({"RISK_PER_TRADE": 0.005})
        assert c.RISK_PER_TRADE == 0.005


# =============================================================================
# 5. Deployment configuration validation
# =============================================================================


class TestDeploymentConfigs:
    """Validate deployment scripts and service files are well-formed."""

    def test_setup_script_exists(self):
        assert (ROOT / "deploy" / "setup.sh").is_file()

    def test_setup_script_has_shebang(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert content.startswith("#!/usr/bin/env bash")

    def test_setup_script_creates_per_account_dirs(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert "data/$ACCT_ID" in content
        assert "logs/$ACCT_ID" in content

    def test_setup_script_validates_accounts_yaml(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert "accounts.yaml" in content
        assert "Validating multi-bot configuration" in content

    def test_setup_script_checks_env_vars(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert "MISSING_ENVS" in content
        assert "REQUIRED_ENVS" in content

    def test_setup_script_runs_preflight(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert "Pre-flight import check" in content
        assert "modules imported successfully" in content

    def test_multi_bot_service_exists(self):
        assert (ROOT / "deploy" / "multi-bot.service").is_file()

    def test_multi_bot_service_has_required_sections(self):
        content = (ROOT / "deploy" / "multi-bot.service").read_text()
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "[Install]" in content
        assert "ExecStart=" in content
        assert "multi_main.py" in content

    def test_multi_bot_service_user(self):
        content = (ROOT / "deploy" / "multi-bot.service").read_text()
        assert "User=trading" in content

    def test_multi_bot_service_restart_policy(self):
        content = (ROOT / "deploy" / "multi-bot.service").read_text()
        assert "Restart=on-failure" in content

    def test_trading_bot_service_exists(self):
        assert (ROOT / "deploy" / "trading-bot.service").is_file()

    def test_trading_bot_service_valid(self):
        content = (ROOT / "deploy" / "trading-bot.service").read_text()
        assert "cest_main.py --schedule" in content
        assert "User=trading" in content

    def test_env_example_exists(self):
        assert (ROOT / ".env.example").is_file()

    def test_env_example_has_required_keys(self):
        content = (ROOT / ".env.example").read_text()
        assert "ALPACA_API_KEY" in content
        assert "ALPACA_SECRET_KEY" in content

    def test_accounts_yaml_exists(self):
        assert (ROOT / "config" / "accounts.yaml").is_file()

    def test_accounts_yaml_parseable(self):
        import yaml
        with open(ROOT / "config" / "accounts.yaml") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, (dict, list))


# =============================================================================
# 6. Multi-account orchestrator
# =============================================================================


class TestMultiAccountConfig:
    """Validate multi-account runner can parse configuration."""

    def test_multi_runner_loads_config(self):
        """MultiAccountRunner requires ACCT*_API_KEY env vars; test with mock."""
        os.environ["ACCT1_API_KEY"] = "test_key_1"
        os.environ["ACCT1_SECRET_KEY"] = "test_secret_1"
        os.environ["ACCT2_API_KEY"] = "test_key_2"
        os.environ["ACCT2_SECRET_KEY"] = "test_secret_2"
        os.environ["ACCT3_API_KEY"] = "test_key_3"
        os.environ["ACCT3_SECRET_KEY"] = "test_secret_3"
        try:
            from multi.runner import MultiAccountRunner
            runner = MultiAccountRunner(config_path="config/accounts.yaml")
            assert isinstance(runner.accounts, list)
            assert len(runner.accounts) >= 1
        finally:
            for k in ["ACCT1_API_KEY", "ACCT1_SECRET_KEY",
                       "ACCT2_API_KEY", "ACCT2_SECRET_KEY",
                       "ACCT3_API_KEY", "ACCT3_SECRET_KEY"]:
                os.environ.pop(k, None)

    def test_account_context_creates_from_config(self):
        from multi.context import AccountContext
        from config.accounts import AccountConfig
        cfg = AccountConfig(
            id="test_acct",
            label="Test Account",
            bot_type="intraday",
            api_key="key",
            secret_key="secret",
            paper=True,
            strategy_overrides={},
        )
        ctx = AccountContext(cfg)
        assert ctx.config.id == "test_acct"
        assert ctx.config.bot_type == "intraday"


# =============================================================================
# 7. Entry point syntax check
# =============================================================================


class TestEntryPointSyntax:
    """Verify entry point files are valid Python (compile without errors)."""

    @pytest.mark.parametrize("script", [
        "main.py", "cest_main.py", "multi_main.py", "gui_main.py",
    ])
    def test_script_compiles(self, script):
        path = ROOT / script
        assert path.is_file(), f"{script} not found"
        source = path.read_text()
        compile(source, str(path), "exec")  # raises SyntaxError on failure


# =============================================================================
# 8. File structure validation
# =============================================================================


class TestProjectStructure:
    """Ensure expected directories and key files exist."""

    @pytest.mark.parametrize("directory", [
        "config", "broker", "strategies", "execution",
        "analysis", "risk", "utils", "multi", "deploy", "tests", "gui",
    ])
    def test_directory_exists(self, directory):
        assert (ROOT / directory).is_dir()

    def test_readme_exists(self):
        assert (ROOT / "README.md").is_file()

    def test_changelog_exists(self):
        assert (ROOT / "CHANGELOG.md").is_file()

    def test_requirements_txt_exists(self):
        assert (ROOT / "requirements.txt").is_file()
