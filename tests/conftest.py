"""Shared fixtures for CEST bot tests."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlcv():
    """Generate 300 bars of synthetic OHLCV data with a mild uptrend."""
    np.random.seed(42)
    n = 300

    # Generate trending price series
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

    # Ensure high >= close and low <= close
    df["high"] = df[["high", "close", "open"]].max(axis=1)
    df["low"] = df[["low", "close", "open"]].min(axis=1)

    return df


@pytest.fixture
def trending_up_data():
    """Generate data with a clear uptrend for regime detection."""
    np.random.seed(100)
    n = 300

    # Strong uptrend: 0.2% daily drift
    returns = np.random.normal(0.002, 0.01, n)
    prices = 100.0 * np.cumprod(1 + returns)

    close = pd.Series(prices)
    high = close * (1 + np.abs(np.random.normal(0, 0.003, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.003, n)))
    volume = pd.Series(np.random.randint(1_000_000, 5_000_000, n), dtype=float)

    df = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]).values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume.values,
    })
    df["high"] = df[["high", "close", "open"]].max(axis=1)
    df["low"] = df[["low", "close", "open"]].min(axis=1)
    return df


@pytest.fixture
def trending_down_data():
    """Generate data with a clear downtrend."""
    np.random.seed(200)
    n = 300

    returns = np.random.normal(-0.002, 0.01, n)
    prices = 200.0 * np.cumprod(1 + returns)

    close = pd.Series(prices)
    high = close * (1 + np.abs(np.random.normal(0, 0.003, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.003, n)))
    volume = pd.Series(np.random.randint(1_000_000, 5_000_000, n), dtype=float)

    df = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]).values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume.values,
    })
    df["high"] = df[["high", "close", "open"]].max(axis=1)
    df["low"] = df[["low", "close", "open"]].min(axis=1)
    return df


@pytest.fixture
def range_data():
    """Generate data with a sideways/ranging market."""
    np.random.seed(300)
    n = 300

    # Mean-reverting around 100 with low volatility
    noise = np.random.normal(0, 0.005, n)
    prices = 100.0 + np.cumsum(noise) * 0.5
    # Pull back toward 100
    for i in range(1, n):
        prices[i] = prices[i - 1] + (100.0 - prices[i - 1]) * 0.05 + noise[i]

    close = pd.Series(prices)
    high = close * (1 + np.abs(np.random.normal(0, 0.002, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.002, n)))
    volume = pd.Series(np.random.randint(500_000, 2_000_000, n), dtype=float)

    df = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]).values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume.values,
    })
    df["high"] = df[["high", "close", "open"]].max(axis=1)
    df["low"] = df[["low", "close", "open"]].min(axis=1)
    return df


@pytest.fixture
def high_vol_data():
    """Generate data with high volatility (for crisis/high_vol regime)."""
    np.random.seed(400)
    n = 300

    # Normal vol for first 200, then spike
    returns = np.concatenate([
        np.random.normal(0.0005, 0.01, 200),
        np.random.normal(-0.005, 0.04, 100),  # High vol crash
    ])
    prices = 150.0 * np.cumprod(1 + returns)

    close = pd.Series(prices)
    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    volume = pd.Series(np.random.randint(1_000_000, 10_000_000, n), dtype=float)

    df = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]).values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": volume.values,
    })
    df["high"] = df[["high", "close", "open"]].max(axis=1)
    df["low"] = df[["low", "close", "open"]].min(axis=1)
    return df
