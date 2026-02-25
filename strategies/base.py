"""Abstract base class that every trading strategy must implement."""

from abc import ABC, abstractmethod
from typing import List

import pandas as pd

from analysis.signals import TradeSignal


class Strategy(ABC):
    """Interface for a trading strategy.

    Subclasses must implement:
    - ``name``          — human-readable label
    - ``indicators()``  — prepare the DataFrame with required indicator columns
    - ``evaluate()``    — inspect the enriched DataFrame and return a TradeSignal
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for logging / display."""

    @abstractmethod
    def indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all indicator columns this strategy needs.

        Must return the same (mutated) DataFrame.
        """

    @abstractmethod
    def evaluate(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """Analyse the indicator-enriched *df* and return a signal."""
