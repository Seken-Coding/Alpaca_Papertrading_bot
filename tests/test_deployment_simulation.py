"""Deployment simulation tests for the intraday-only bot."""

import importlib
import os
from pathlib import Path

import pytest

# Ensure env vars are set so Settings() doesn't crash
os.environ.setdefault("ALPACA_API_KEY", "test_deploy_key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_deploy_secret")
os.environ.setdefault("ALPACA_PAPER", "true")
os.environ.setdefault("AUTO_EXECUTE", "false")

ROOT = Path(__file__).resolve().parent.parent


class TestDependencies:
    """Verify required packages are importable."""

    @pytest.mark.parametrize("package", ["alpaca", "pandas", "numpy", "dotenv"])
    def test_core_dependency_importable(self, package):
        mod = importlib.import_module(package)
        assert mod is not None

    def test_requirements_file_exists(self):
        assert (ROOT / "requirements.txt").is_file()

    def test_requirements_parseable(self):
        lines = (ROOT / "requirements.txt").read_text().splitlines()
        pkg_lines = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
        assert len(pkg_lines) >= 4


ALL_MODULES = [
    "config.settings",
    "broker.client",
    "broker.errors",
    "strategies.momentum",
    "strategies.mean_reversion",
    "strategies.scanner",
    "strategies.screener",
    "execution.engine",
    "execution.position_store",
    "execution.trade_journal",
    "execution.position_monitor",
    "execution.market_regime",
    "analysis.indicators",
    "analysis.scorer",
    "analysis.signals",
    "analysis.data_loader",
    "risk.manager",
    "utils.bar_cache",
    "logging_config",
]


class TestModuleImports:
    """Every intraday module must import without errors."""

    @pytest.mark.parametrize("module_name", ALL_MODULES)
    def test_module_imports(self, module_name):
        mod = importlib.import_module(module_name)
        assert mod is not None


class TestIntradayBotInit:
    """Simulate intraday bot startup — everything up to Alpaca connection."""

    def test_settings_load(self):
        from config.settings import settings

        assert settings.paper is True
        assert settings.auto_execute is False
        assert settings.scan_interval_min > 0
        assert settings.max_orders_per_scan > 0

    def test_risk_manager_init(self):
        from risk.manager import RiskConfig, RiskManager

        rm = RiskManager(RiskConfig())
        rm.set_session_equity(100_000)

    def test_strategies_instantiate(self):
        from strategies.mean_reversion import MeanReversionStrategy
        from strategies.momentum import MomentumStrategy

        assert MomentumStrategy() is not None
        assert MeanReversionStrategy() is not None

    def test_position_store_init(self):
        from execution.position_store import PositionStore

        assert PositionStore() is not None

    def test_trade_journal_init(self):
        from execution.trade_journal import TradeJournal

        assert TradeJournal() is not None


class TestDeploymentConfigs:
    """Validate deployment scripts and service files are intraday-only."""

    def test_setup_script_exists(self):
        assert (ROOT / "deploy" / "setup.sh").is_file()

    def test_setup_script_has_shebang(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert content.startswith("#!/usr/bin/env bash")

    def test_setup_script_validates_env(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert "Validating intraday configuration" in content
        assert "ALPACA_API_KEY is missing or empty" in content
        assert "ALPACA_SECRET_KEY is missing or empty" in content

    def test_setup_script_installs_intraday_service(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert 'TARGET_SERVICE="intraday-bot"' in content
        assert "intraday-bot.service" in content
        assert "trading-bot.service" not in content

    def test_setup_script_runs_preflight(self):
        content = (ROOT / "deploy" / "setup.sh").read_text()
        assert "pre-flight import check" in content.lower()
        assert "modules imported successfully" in content

    def test_intraday_service_exists(self):
        assert (ROOT / "deploy" / "intraday-bot.service").is_file()

    def test_intraday_service_targets_main(self):
        content = (ROOT / "deploy" / "intraday-bot.service").read_text()
        assert "ExecStart=/opt/trading-bot/venv/bin/python main.py" in content

    def test_trading_bot_service_removed(self):
        assert not (ROOT / "deploy" / "trading-bot.service").exists()


class TestIntradayOnlyLayout:
    """Validate legacy non-intraday artifacts are removed."""

    @pytest.mark.parametrize(
        "removed_path",
        [
            "cest_main.py",
            "config/cest_settings.py",
            "config/universe.py",
            "analysis/cest_indicators.py",
            "broker/alpaca_broker.py",
            "broker/base.py",
            "broker/ib_broker.py",
            "risk/cest_risk_manager.py",
            "risk/position_sizing.py",
            "risk/gap_protection.py",
            "utils/state.py",
            "utils/trade_tracker.py",
            "deploy/trading-bot.service",
        ],
    )
    def test_legacy_artifacts_removed(self, removed_path):
        assert not (ROOT / removed_path).exists()


class TestEntryPointSyntax:
    """Verify entry point files compile without syntax errors."""

    @pytest.mark.parametrize("script", ["main.py", "gui_main.py"])
    def test_script_compiles(self, script):
        path = ROOT / script
        assert path.is_file(), f"{script} not found"
        compile(path.read_text(), str(path), "exec")


class TestProjectStructure:
    """Ensure expected directories and key files exist."""

    @pytest.mark.parametrize(
        "directory",
        ["config", "broker", "strategies", "execution", "analysis", "risk", "utils", "deploy", "tests", "gui"],
    )
    def test_directory_exists(self, directory):
        assert (ROOT / directory).is_dir()

    def test_readme_exists(self):
        assert (ROOT / "README.md").is_file()

    def test_requirements_txt_exists(self):
        assert (ROOT / "requirements.txt").is_file()
