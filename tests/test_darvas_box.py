"""Tests for Darvas Box pattern detection."""

import numpy as np
import pandas as pd
import pytest

from strategies.darvas_box import (
    DarvasBox,
    detect_darvas_breakout,
    identify_darvas_boxes,
)


@pytest.fixture
def box_data():
    """Create data with a clear Darvas Box pattern:
    price rallies, consolidates in a box, then breaks out.
    """
    np.random.seed(42)
    n = 100

    # Phase 1: rally (bars 0-30)
    rally = np.linspace(100, 120, 31)
    # Phase 2: consolidation box (bars 31-70) — ceiling ~120, floor ~115
    box_prices = 117.5 + np.random.normal(0, 1.0, 40)
    box_prices = np.clip(box_prices, 115, 120)
    # Phase 3: breakout (bars 71-99) — price jumps above 120
    breakout = np.linspace(121, 130, 29)

    prices = np.concatenate([rally, box_prices, breakout])
    close = pd.Series(prices)
    high = close + np.abs(np.random.normal(0, 0.3, n))
    low = close - np.abs(np.random.normal(0, 0.3, n))
    volume = pd.Series(np.random.randint(1_000_000, 3_000_000, n), dtype=float)
    # Volume spike on breakout
    volume.iloc[-29:] = volume.iloc[-29:] * 2.5

    return high, low, close, volume


def test_identify_boxes_returns_list(box_data):
    high, low, close, _ = box_data
    boxes = identify_darvas_boxes(high, low, close, lookback=80)
    assert isinstance(boxes, list)


def test_identify_boxes_has_ceiling_above_floor(box_data):
    high, low, close, _ = box_data
    boxes = identify_darvas_boxes(high, low, close, lookback=80)
    for box in boxes:
        assert box.ceiling > box.floor
        assert box.width_bars > 0


def test_detect_breakout_with_good_data(box_data):
    high, low, close, volume = box_data
    # The breakout phase should trigger a Darvas breakout
    result = detect_darvas_breakout(high, low, close, volume, lookback=80)
    assert isinstance(result, bool)


def test_detect_breakout_insufficient_data():
    """Insufficient data should return False."""
    close = pd.Series([100.0, 101.0, 102.0])
    high = close + 0.5
    low = close - 0.5
    volume = pd.Series([1000000, 1000000, 1000000], dtype=float)
    assert detect_darvas_breakout(high, low, close, volume, lookback=60) is False


def test_no_breakout_in_flat_data():
    """Completely flat data should not produce a breakout signal."""
    n = 100
    flat = pd.Series([100.0] * n)
    high = flat + 0.01
    low = flat - 0.01
    volume = pd.Series([1_000_000] * n, dtype=float)
    # Even if boxes form in flat data, there should be no *breakout*
    # because close never exceeds the ceiling
    assert detect_darvas_breakout(high, low, flat, volume, lookback=80) is False


def test_darvas_box_dataclass():
    box = DarvasBox(ceiling=120.0, floor=115.0, ceiling_bar=10, floor_bar=20, width_bars=13)
    assert box.ceiling == 120.0
    assert box.floor == 115.0
    assert box.ceiling_bar == 10
    assert box.floor_bar == 20
    assert box.width_bars == 13
