"""Tests for gap risk protection module."""

import pytest
from unittest.mock import MagicMock

from risk.gap_protection import (
    GAP_ATR_MULTIPLIER,
    MAX_LOSS_R_MULTIPLE,
    PORTFOLIO_GAP_LOSS_PCT,
    check_portfolio_gap_risk,
    check_position_gap_risk,
)


def _make_trade(
    symbol="AAPL",
    direction="LONG",
    entry_price=100.0,
    stop_loss=95.0,
    initial_risk=5.0,
):
    trade = MagicMock()
    trade.symbol = symbol
    trade.direction = direction
    trade.entry_price = entry_price
    trade.stop_loss = stop_loss
    trade.initial_risk = initial_risk
    return trade


class TestPositionGapRisk:
    def test_no_gap_returns_hold(self):
        trade = _make_trade()
        result = check_position_gap_risk(
            trade, current_open=100.5, current_close=101.0,
            prev_close=100.0, atr_val=2.0,
        )
        assert result.action == "HOLD"
        assert result.severity == "NORMAL"

    def test_blown_stop_large_gap(self):
        """Gap that jumps past stop by >5×ATR should trigger EXIT."""
        trade = _make_trade(stop_loss=95.0)
        # ATR=2, gap > 5*2=10 past stop → open at 84 (11 points past stop)
        result = check_position_gap_risk(
            trade, current_open=84.0, current_close=85.0,
            prev_close=100.0, atr_val=2.0,
        )
        assert result.action == "EXIT"
        assert result.severity == "CRITICAL"
        assert "Blown stop" in result.reason

    def test_max_loss_cap(self):
        """Loss exceeding 3R should trigger EXIT (when stop NOT blown by gap)."""
        # Entry=100, stop=80 (risk=20), open=81 (above stop, NOT blown),
        # close=38 → loss=62, R=62/20=3.1R > 3R cap. Gap ATR = |81-99|/2=9
        # but open > stop so gap is not adverse for blown-stop check.
        trade = _make_trade(entry_price=100.0, stop_loss=80.0, initial_risk=20.0)
        result = check_position_gap_risk(
            trade, current_open=81.0, current_close=38.0,
            prev_close=99.0, atr_val=2.0,
        )
        assert result.action == "EXIT"
        assert "Max loss cap" in result.reason

    def test_flash_crash_holds(self):
        """10%+ single-bar drop should hold (not sell into crash),
        but only when stop is NOT blown and loss is within 3R cap."""
        # Entry at 100, stop at 80, risk=20. Price drops 12% to 88.
        # Open at 92 — above stop (80), so stop is NOT blown.
        # Loss = 12/20 = 0.6R, within 3R cap. Flash crash filter kicks in.
        trade = _make_trade(entry_price=100.0, stop_loss=80.0, initial_risk=20.0)
        result = check_position_gap_risk(
            trade, current_open=92.0, current_close=88.0,
            prev_close=100.0, atr_val=2.0,
        )
        assert result.action == "HOLD"
        assert "Flash crash" in result.reason

    def test_short_position_gap_up(self):
        """Short position with adverse gap up past stop."""
        trade = _make_trade(direction="SHORT", entry_price=100.0, stop_loss=105.0, initial_risk=5.0)
        # Gap up past stop by >5×ATR
        result = check_position_gap_risk(
            trade, current_open=118.0, current_close=119.0,
            prev_close=100.0, atr_val=2.0,
        )
        assert result.action == "EXIT"
        assert result.severity == "CRITICAL"

    def test_minor_adverse_gap_holds(self):
        """Small gap past stop (within tolerance) should hold."""
        trade = _make_trade(stop_loss=95.0)
        # Small gap: open at 94, ATR=2, gap past stop = 1, < 5*2=10
        result = check_position_gap_risk(
            trade, current_open=94.0, current_close=94.5,
            prev_close=96.0, atr_val=2.0,
        )
        assert result.action == "HOLD"

    def test_zero_atr_returns_hold(self):
        trade = _make_trade()
        result = check_position_gap_risk(
            trade, current_open=100.0, current_close=100.0,
            prev_close=100.0, atr_val=0.0,
        )
        assert result.action == "HOLD"


class TestPortfolioGapRisk:
    def test_no_emergency_when_ok(self):
        positions = [
            {"symbol": "AAPL", "unrealized_pl": -100},
            {"symbol": "MSFT", "unrealized_pl": 200},
        ]
        triggered, loss_pct = check_portfolio_gap_risk(100_000, positions)
        assert triggered is False

    def test_emergency_on_large_loss(self):
        positions = [
            {"symbol": "AAPL", "unrealized_pl": -3000},
            {"symbol": "MSFT", "unrealized_pl": -3000},
        ]
        triggered, loss_pct = check_portfolio_gap_risk(100_000, positions)
        assert triggered is True
        assert loss_pct > PORTFOLIO_GAP_LOSS_PCT

    def test_empty_positions(self):
        triggered, loss_pct = check_portfolio_gap_risk(100_000, [])
        assert triggered is False
        assert loss_pct == 0.0

    def test_zero_equity(self):
        triggered, loss_pct = check_portfolio_gap_risk(0, [{"unrealized_pl": -100}])
        assert triggered is False
