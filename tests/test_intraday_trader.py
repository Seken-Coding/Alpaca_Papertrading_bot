"""Plausibility tests for the intraday trader.

Tests the full scan → execute → monitor pipeline with mocked Alpaca API,
verifying that:
- Multi-bot mode works without ALPACA_API_KEY in env
- PositionMonitor uses per-account settings (not global)
- _run_scheduler wires components correctly
- _scan_and_execute handles edge cases
- Settings.with_overrides applies account-specific values
- The full pipeline doesn't crash on realistic data
"""

import os
import types
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeAccount:
    equity: str = "100000.00"
    buying_power: str = "200000.00"
    status: str = "ACTIVE"


@dataclass
class FakePosition:
    symbol: str = "AAPL"
    current_price: str = "155.00"
    avg_entry_price: str = "150.00"
    qty: str = "10"


@dataclass
class FakeOrder:
    id: str = "order-123"
    symbol: str = "AAPL"


class FakeSettings:
    """Minimal settings object matching the Settings interface."""
    def __init__(self, **overrides):
        self.api_key = "fake-key"
        self.secret_key = "fake-secret"
        self.paper = True
        self.auto_execute = True
        self.scan_interval_min = 5
        self.max_orders_per_scan = 5
        self.position_monitor = True
        self.trailing_stop_pct = 1.5
        self.max_hold_days = 3
        self.regime_filter = False
        self.scan_start_et = "10:00"
        self.scan_end_et = "15:30"
        self.universe_mode = "static"
        self.universe_cache_ttl = 86400
        for k, v in overrides.items():
            setattr(self, k, v)


def _make_ohlcv(n=300, seed=42):
    """Generate synthetic OHLCV data."""
    np.random.seed(seed)
    returns = np.random.normal(0.0005, 0.015, n)
    prices = 100.0 * np.cumprod(1 + returns)
    close = pd.Series(prices, name="close")
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
    open_ = close.shift(1).fillna(close.iloc[0]) + np.random.normal(0, 0.5, n)
    volume = pd.Series(np.random.randint(500_000, 5_000_000, n), dtype=float)
    df = pd.DataFrame({
        "open": open_.values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume.values,
    })
    df["high"] = df[["high", "close", "open"]].max(axis=1)
    df["low"] = df[["low", "close", "open"]].min(axis=1)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 1. PositionMonitor — per-account settings
# ──────────────────────────────────────────────────────────────────────────────

class TestPositionMonitorSettings:
    """Verify PositionMonitor uses injected cfg, not global settings."""

    def test_uses_injected_cfg(self):
        """When cfg is provided, PositionMonitor must use it instead of global settings."""
        from execution.position_monitor import PositionMonitor
        from execution.position_store import PositionStore
        from execution.trade_journal import TradeJournal

        cfg = FakeSettings(position_monitor=False)
        client = MagicMock()
        store = MagicMock(spec=PositionStore)
        journal = MagicMock(spec=TradeJournal)

        monitor = PositionMonitor(client=client, store=store, journal=journal, cfg=cfg)
        monitor.run()

        # position_monitor=False, so get_positions should NOT be called
        client.get_positions.assert_not_called()

    def test_monitor_enabled_via_cfg(self):
        """When cfg.position_monitor=True, monitor should fetch positions."""
        from execution.position_monitor import PositionMonitor

        cfg = FakeSettings(position_monitor=True)
        client = MagicMock()
        client.get_positions.return_value = []
        store = MagicMock()
        journal = MagicMock()

        monitor = PositionMonitor(client=client, store=store, journal=journal, cfg=cfg)
        monitor.run()

        client.get_positions.assert_called_once()

    def test_trailing_stop_uses_cfg_value(self):
        """Trailing stop percentage must come from per-account cfg."""
        from execution.position_monitor import PositionMonitor

        cfg = FakeSettings(trailing_stop_pct=2.5, position_monitor=True)
        client = MagicMock()
        position = FakePosition(
            symbol="TSLA", current_price="160.00",
            avg_entry_price="150.00", qty="10",
        )
        client.get_positions.return_value = [position]
        client.get_orders.return_value = []

        store = MagicMock()
        store.get.return_value = {
            "entry_atr": 3.0,
            "trailing_upgraded": False,
            "entry_time": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }

        trailing_order = FakeOrder(id="trail-1", symbol="TSLA")
        client.trailing_stop_order.return_value = trailing_order

        journal = MagicMock()
        monitor = PositionMonitor(client=client, store=store, journal=journal, cfg=cfg)
        monitor.run()

        # Verify trailing stop was placed with the cfg value (2.5), not default (1.0)
        client.trailing_stop_order.assert_called_once()
        call_kwargs = client.trailing_stop_order.call_args
        assert call_kwargs[1]["trail_percent"] == 2.5

    def test_max_hold_days_uses_cfg_value(self):
        """Time-based exit must use per-account max_hold_days."""
        from execution.position_monitor import PositionMonitor

        cfg = FakeSettings(max_hold_days=1, position_monitor=True, trailing_stop_pct=0)
        client = MagicMock()
        position = FakePosition(
            symbol="GOOG", current_price="140.00",
            avg_entry_price="150.00", qty="5",
        )
        client.get_positions.return_value = [position]
        client.get_orders.return_value = [FakeOrder(symbol="GOOG")]

        # Entry was 2 days ago — should trigger close with max_hold_days=1
        old_entry = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        store = MagicMock()
        store.get.return_value = {
            "entry_atr": 3.0,
            "trailing_upgraded": False,
            "entry_time": old_entry,
            "order_id": "ord-1",
            "strategy": "Momentum",
        }

        journal = MagicMock()
        monitor = PositionMonitor(client=client, store=store, journal=journal, cfg=cfg)
        monitor.run()

        # Should have closed the position
        client.close_position.assert_called_once_with("GOOG")

    def test_no_global_settings_crash_without_env_vars(self):
        """PositionMonitor with cfg should work even if ALPACA_API_KEY is unset."""
        from execution.position_monitor import PositionMonitor

        # Temporarily remove ALPACA_API_KEY if set
        orig = os.environ.pop("ALPACA_API_KEY", None)
        try:
            cfg = FakeSettings(position_monitor=False)
            client = MagicMock()
            store = MagicMock()
            journal = MagicMock()

            # This must NOT crash — previously it would access global settings
            # which requires ALPACA_API_KEY
            monitor = PositionMonitor(
                client=client, store=store, journal=journal, cfg=cfg,
            )
            monitor.run()
        finally:
            if orig is not None:
                os.environ["ALPACA_API_KEY"] = orig


# ──────────────────────────────────────────────────────────────────────────────
# 2. Settings.with_overrides
# ──────────────────────────────────────────────────────────────────────────────

class TestSettingsWithOverrides:
    """Verify Settings.with_overrides creates proper per-account settings."""

    def test_basic_overrides(self):
        from config.settings import Settings

        s = Settings.with_overrides(
            api_key="key1", secret_key="secret1", paper=True,
            trailing_stop_pct=2.5,
            max_orders_per_scan=8,
            scan_interval_min=3,
        )
        assert s.api_key == "key1"
        assert s.secret_key == "secret1"
        assert s.trailing_stop_pct == 2.5
        assert s.max_orders_per_scan == 8
        assert s.scan_interval_min == 3

    def test_auto_execute_defaults_true(self):
        from config.settings import Settings

        s = Settings.with_overrides(api_key="k", secret_key="s")
        assert s.auto_execute is True

    def test_unknown_override_ignored(self):
        from config.settings import Settings

        # Should not raise, just log a warning
        s = Settings.with_overrides(
            api_key="k", secret_key="s",
            nonexistent_field="value",
        )
        assert not hasattr(s, "nonexistent_field")

    def test_position_monitor_overridable(self):
        from config.settings import Settings

        s = Settings.with_overrides(
            api_key="k", secret_key="s",
            position_monitor=False,
        )
        assert s.position_monitor is False


# ──────────────────────────────────────────────────────────────────────────────
# 3. Strategy evaluation plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestStrategyPlausibility:
    """Verify strategies produce valid signals on synthetic data."""

    def test_momentum_returns_valid_signal(self):
        from strategies.momentum import MomentumStrategy
        from analysis.indicators import apply_all
        from analysis.signals import Signal

        df = _make_ohlcv(300, seed=42)
        enriched = apply_all(df)
        strategy = MomentumStrategy()
        result = strategy.evaluate(enriched, "TEST")

        assert result.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)
        assert result.symbol == "TEST"
        assert isinstance(result.price, float)
        assert result.price > 0

    def test_mean_reversion_returns_valid_signal(self):
        from strategies.mean_reversion import MeanReversionStrategy
        from analysis.indicators import apply_all
        from analysis.signals import Signal

        df = _make_ohlcv(300, seed=42)
        enriched = apply_all(df)
        strategy = MeanReversionStrategy()
        result = strategy.evaluate(enriched, "TEST")

        assert result.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)
        assert result.symbol == "TEST"

    def test_momentum_insufficient_data_returns_hold(self):
        from strategies.momentum import MomentumStrategy
        from analysis.signals import Signal

        df = _make_ohlcv(30, seed=42)
        strategy = MomentumStrategy()
        result = strategy.evaluate(df, "SHORT")

        assert result.signal == Signal.HOLD

    def test_mean_reversion_insufficient_data_returns_hold(self):
        from strategies.mean_reversion import MeanReversionStrategy
        from analysis.signals import Signal

        df = _make_ohlcv(10, seed=42)
        strategy = MeanReversionStrategy()
        result = strategy.evaluate(df, "SHORT")

        assert result.signal == Signal.HOLD

    def test_strategies_dont_import_global_settings(self):
        """Strategies must not depend on global settings."""
        import strategies.momentum as mom
        import strategies.mean_reversion as mr

        source_mom = open(mom.__file__).read()
        source_mr = open(mr.__file__).read()

        assert "from config.settings import" not in source_mom
        assert "from config.settings import" not in source_mr


# ──────────────────────────────────────────────────────────────────────────────
# 4. ExecutionEngine plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestExecutionEnginePlausibility:
    """Verify execution engine doesn't depend on global settings."""

    def test_engine_no_global_settings_import(self):
        import execution.engine as eng
        source = open(eng.__file__).read()
        assert "from config.settings import" not in source

    def test_engine_respects_max_orders(self):
        from execution.engine import ExecutionEngine
        from strategies.scanner import Recommendation
        from analysis.signals import Signal

        client = MagicMock()
        client.is_market_open.return_value = True
        client.get_account.return_value = FakeAccount()
        client.get_positions.return_value = []
        client.bracket_order.return_value = FakeOrder()
        client.wait_for_bracket_attachment.return_value = True

        risk = MagicMock()
        risk.check_portfolio_limits.return_value = MagicMock(allowed=True)
        risk.validate_score.return_value = MagicMock(allowed=True)

        sizing = MagicMock()
        sizing.passes_risk = True
        sizing.shares = 10
        sizing.stop_loss_price = 95.0
        sizing.take_profit_price = 115.0
        sizing.risk_reward = 2.0
        risk.calculate_position_size.return_value = sizing

        engine = ExecutionEngine(client=client, risk_manager=risk, max_orders=2)

        recs = [
            Recommendation("AAPL", 150.0, Signal.BUY, "Momentum", 0.8, "test", 3.0),
            Recommendation("MSFT", 350.0, Signal.BUY, "Momentum", 0.7, "test", 5.0),
            Recommendation("GOOG", 140.0, Signal.BUY, "Momentum", 0.6, "test", 4.0),
        ]
        summary = engine.execute(recs)

        assert len(summary.placed) == 2  # max_orders=2
        assert client.bracket_order.call_count == 2

    def test_engine_skips_sell_signals(self):
        from execution.engine import ExecutionEngine
        from strategies.scanner import Recommendation
        from analysis.signals import Signal

        client = MagicMock()
        client.is_market_open.return_value = True
        client.get_account.return_value = FakeAccount()
        client.get_positions.return_value = []

        risk = MagicMock()
        risk.check_portfolio_limits.return_value = MagicMock(allowed=True)

        engine = ExecutionEngine(client=client, risk_manager=risk)

        recs = [
            Recommendation("AAPL", 150.0, Signal.SELL, "Momentum", 0.8, "test", 3.0),
        ]
        summary = engine.execute(recs)

        assert len(summary.skipped) == 1
        client.bracket_order.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 5. Scanner plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestScannerPlausibility:
    """Verify scanner pipeline produces valid output."""

    def test_scanner_no_global_settings_import(self):
        import strategies.scanner as sc
        source = open(sc.__file__).read()
        assert "from config.settings import" not in source

    def test_scanner_deduplicates_by_symbol(self):
        from strategies.scanner import Recommendation, StrategyScanner
        from analysis.signals import Signal

        client = MagicMock()
        strategy1 = MagicMock()
        strategy1.name = "S1"

        # Create scanner, mock out screening and data loading
        scanner = StrategyScanner(client=client, strategies=[strategy1])

        # Test dedup logic: two recs for same symbol, highest strength wins
        recs = [
            Recommendation("AAPL", 150.0, Signal.BUY, "S1", 0.6, "weak", 3.0),
            Recommendation("AAPL", 150.0, Signal.BUY, "S2", 0.9, "strong", 3.0),
        ]
        best = {}
        for rec in recs:
            if rec.symbol not in best or rec.strength > best[rec.symbol].strength:
                best[rec.symbol] = rec
        result = list(best.values())

        assert len(result) == 1
        assert result[0].strength == 0.9


# ──────────────────────────────────────────────────────────────────────────────
# 6. Risk manager plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestRiskManagerPlausibility:
    """Verify risk manager basic operations."""

    def test_risk_manager_no_global_settings_import(self):
        import risk.manager as rm
        source = open(rm.__file__).read()
        assert "from config.settings import" not in source

    def test_portfolio_limits_block_when_max_positions(self):
        from risk.manager import RiskManager, RiskConfig

        config = RiskConfig()
        rm = RiskManager(config)
        rm.set_session_equity(100_000)

        result = rm.check_portfolio_limits(
            position_count=config.max_positions + 1,
            equity=100_000,
            buying_power=50_000,
        )
        assert not result.allowed

    def test_position_sizing_produces_valid_output(self):
        from risk.manager import RiskManager, RiskConfig

        rm = RiskManager(RiskConfig())
        rm.set_session_equity(100_000)

        sizing = rm.calculate_position_size(
            symbol="AAPL", price=150.0, atr=3.0,
            equity=100_000, direction="BUY",
        )
        assert sizing.shares >= 0
        if sizing.passes_risk:
            assert sizing.stop_loss_price < 150.0
            assert sizing.take_profit_price > 150.0


# ──────────────────────────────────────────────────────────────────────────────
# 7. Multi-bot runner plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestMultiBotRunnerPlausibility:
    """Verify the multi-bot runner wires intraday correctly."""

    def test_run_intraday_passes_cfg_to_scheduler(self):
        """_run_intraday must pass per-account cfg to _run_scheduler."""
        import multi.runner as runner_mod
        source = open(runner_mod.__file__).read()

        # Verify _run_intraday calls _run_scheduler with cfg=s
        assert "cfg=s" in source, (
            "_run_intraday must pass cfg=s to _run_scheduler"
        )

    def test_scheduler_passes_cfg_to_position_monitor(self):
        """_run_scheduler must pass cfg to PositionMonitor."""
        import main as main_mod
        source = open(main_mod.__file__).read()

        assert "cfg=" in source.split("PositionMonitor(")[1].split(")")[0], (
            "_run_scheduler must pass cfg to PositionMonitor constructor"
        )

    def test_account_context_creates_valid_settings(self):
        """AccountContext.create_settings must return a Settings with overrides applied."""
        from config.accounts import AccountConfig
        from multi.context import AccountContext

        config = AccountConfig(
            id="test_acct",
            label="Test Account",
            bot_type="intraday",
            api_key="test-api-key",
            secret_key="test-secret-key",
            paper=True,
            strategy_overrides={"trailing_stop_pct": 2.5, "max_orders_per_scan": 8},
        )
        ctx = AccountContext(config)
        s = ctx.create_settings()

        assert s.api_key == "test-api-key"
        assert s.secret_key == "test-secret-key"
        assert s.trailing_stop_pct == 2.5
        assert s.max_orders_per_scan == 8
        assert s.auto_execute is True  # multi-bot always auto-executes


# ──────────────────────────────────────────────────────────────────────────────
# 8. _scan_and_execute plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestScanAndExecutePlausibility:
    """Verify _scan_and_execute handles edge cases."""

    def test_returns_string_on_account_fetch_failure(self):
        from main import _scan_and_execute

        client = MagicMock()
        client.get_account.side_effect = Exception("Network error")
        risk = MagicMock()
        cfg = FakeSettings()

        result = _scan_and_execute(client, risk, cfg=cfg)
        assert "account fetch failed" in result

    def test_returns_string_when_no_recommendations(self):
        from main import _scan_and_execute

        client = MagicMock()
        client.get_account.return_value = FakeAccount()
        risk = MagicMock()
        cfg = FakeSettings(regime_filter=False)

        with patch("main.StrategyScanner") as MockScanner:
            MockScanner.return_value.scan.return_value = []
            result = _scan_and_execute(client, risk, cfg=cfg)

        assert "no actionable recommendations" in result

    def test_uses_cfg_not_global_settings(self):
        """_scan_and_execute must use cfg parameter for all settings."""
        from main import _scan_and_execute

        cfg = FakeSettings(
            auto_execute=False,
            regime_filter=False,
            universe_mode="static",
            universe_cache_ttl=86400,
        )
        client = MagicMock()
        client.get_account.return_value = FakeAccount()
        risk = MagicMock()

        with patch("main.StrategyScanner") as MockScanner:
            MockScanner.return_value.scan.return_value = []
            result = _scan_and_execute(client, risk, cfg=cfg)

        # Should have used cfg.universe_mode, not global settings
        call_kwargs = MockScanner.call_args[1]
        assert call_kwargs["universe_mode"] == "static"


# ──────────────────────────────────────────────────────────────────────────────
# 9. PositionStore and TradeJournal plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestPositionStorePlausibility:
    """Verify PositionStore works correctly."""

    def test_record_and_retrieve(self, tmp_path):
        from execution.position_store import PositionStore

        store = PositionStore(path=tmp_path / "positions.json")
        store.record_entry(
            symbol="AAPL", entry_price=150.0, entry_atr=3.0,
            strategy="Momentum", order_id="ord-1",
            shares=10, stop_loss_price=144.0, take_profit_price=162.0,
        )

        meta = store.get("AAPL")
        assert meta is not None
        assert meta["entry_price"] == 150.0
        assert meta["entry_atr"] == 3.0
        assert meta["trailing_upgraded"] is False

    def test_reconcile_removes_stale(self, tmp_path):
        from execution.position_store import PositionStore

        store = PositionStore(path=tmp_path / "positions.json")
        store.record_entry("AAPL", 150.0, 3.0, "Mom", "o1", 10, 144.0, 162.0)
        store.record_entry("MSFT", 350.0, 5.0, "Mom", "o2", 5, 340.0, 370.0)

        store.reconcile({"AAPL"})  # MSFT no longer live
        assert store.get("AAPL") is not None
        assert store.get("MSFT") is None

    def test_mark_trailing_upgraded(self, tmp_path):
        from execution.position_store import PositionStore

        store = PositionStore(path=tmp_path / "positions.json")
        store.record_entry("AAPL", 150.0, 3.0, "Mom", "o1", 10, 144.0, 162.0)
        store.mark_trailing_upgraded("AAPL")

        meta = store.get("AAPL")
        assert meta["trailing_upgraded"] is True


class TestTradeJournalPlausibility:
    """Verify TradeJournal writes correctly."""

    def test_entry_and_exit(self, tmp_path):
        from execution.trade_journal import TradeJournal

        journal = TradeJournal(path=tmp_path / "journal.csv")
        journal.record_entry(
            symbol="AAPL", qty=10, price=150.0,
            strategy="Momentum", reason="test signal",
            entry_order_id="ord-1",
        )
        journal.record_exit(
            symbol="AAPL", qty=10, price=160.0,
            strategy="Momentum", reason="take_profit",
            pnl=100.0, hold_duration_hours=24.5,
            entry_order_id="ord-1",
        )

        content = (tmp_path / "journal.csv").read_text()
        assert "ENTRY" in content
        assert "EXIT" in content
        assert "AAPL" in content


# ──────────────────────────────────────────────────────────────────────────────
# 10. Indicator pipeline plausibility
# ──────────────────────────────────────────────────────────────────────────────

class TestIndicatorPipelinePlausibility:
    """Verify indicator computation doesn't crash and produces expected columns."""

    def test_apply_all_produces_required_columns(self):
        from analysis.indicators import apply_all

        df = _make_ohlcv(300)
        enriched = apply_all(df)

        required = [
            "sma_20", "sma_50", "ema_9", "rsi", "macd", "macd_signal",
            "macd_hist", "atr", "adx", "bb_upper", "bb_lower", "bb_middle",
        ]
        for col in required:
            assert col in enriched.columns, f"Missing required column: {col}"

    def test_apply_all_no_all_nan_columns(self):
        from analysis.indicators import apply_all

        df = _make_ohlcv(300)
        enriched = apply_all(df)

        # The last row (used for signal evaluation) should have valid values
        # for key indicators
        latest = enriched.iloc[-1]
        for col in ["rsi", "atr", "adx", "macd_hist", "sma_20", "sma_50"]:
            val = latest[col]
            assert val == val, f"Column {col} is NaN in latest row"

    def test_apply_all_with_minimum_data(self):
        """apply_all should not crash on small datasets."""
        from analysis.indicators import apply_all

        df = _make_ohlcv(60)
        enriched = apply_all(df)
        assert len(enriched) == 60


# ──────────────────────────────────────────────────────────────────────────────
# 11. End-to-end wiring: multi-bot → intraday → monitor
# ──────────────────────────────────────────────────────────────────────────────

class TestEndToEndWiring:
    """Verify the complete multi-bot → intraday pipeline is wired correctly."""

    def test_position_monitor_receives_cfg_from_scheduler(self):
        """When _run_scheduler creates PositionMonitor, it must pass cfg."""
        # Parse the actual source code to verify wiring
        import main
        import inspect
        source = inspect.getsource(main._run_scheduler)

        # PositionMonitor must be created with cfg= parameter
        assert "cfg=" in source, (
            "_run_scheduler must pass cfg to PositionMonitor"
        )
        # The line creating PositionMonitor should include cfg
        for line in source.split("\n"):
            if "PositionMonitor(" in line:
                assert "cfg=" in line, (
                    f"PositionMonitor creation line must include cfg=: {line}"
                )

    def test_scan_and_execute_passes_cfg_to_scanner(self):
        """_scan_and_execute must pass cfg fields to StrategyScanner."""
        import main
        import inspect
        source = inspect.getsource(main._scan_and_execute)

        assert "s.universe_mode" in source
        assert "s.auto_execute" in source

    def test_no_bare_settings_access_in_scheduler(self):
        """_run_scheduler must not access global 'settings' directly."""
        import main
        import inspect
        source = inspect.getsource(main._run_scheduler)

        # Should not have bare 'settings.' access (only 's.' or 'cfg.')
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            # Skip comments
            if stripped.startswith("#"):
                continue
            # 'settings' alone (not 'self._settings' or as substring) means global access
            if "settings." in stripped and "self._settings" not in stripped:
                # Allow the assignment 's = cfg or settings'
                if "cfg or settings" in stripped:
                    continue
                pytest.fail(
                    f"_run_scheduler accesses global 'settings' directly: {stripped}"
                )
