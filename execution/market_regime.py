"""Market regime filter — classifies the broad market before each scan.

Uses SPY's SMA-200 and 5-day momentum to determine regime:
    BULL    — SPY > SMA-200 AND 5-day momentum positive
    BEAR    — SPY < SMA-200 AND 5-day momentum negative
    NEUTRAL — mixed signals

When REGIME_FILTER=true in .env, BEAR regime blocks all new BUY entries.
"""

import logging

from alpaca.data.timeframe import TimeFrame

from broker.client import AlpacaClient
from analysis.data_loader import load_bars_single

logger = logging.getLogger(__name__)

_SPY = "SPY"
_SMA_PERIOD = 200
_MOMENTUM_DAYS = 5
_MIN_BARS = _SMA_PERIOD + _MOMENTUM_DAYS + 5


class MarketRegimeFilter:
    """Classify the current market regime from SPY daily bars."""

    def __init__(self, client: AlpacaClient):
        self.client = client

    def classify(self) -> str:
        """Return 'BULL', 'BEAR', or 'NEUTRAL'.

        Returns 'NEUTRAL' on any data or computation failure.
        """
        try:
            df = load_bars_single(
                self.client,
                symbol=_SPY,
                timeframe=TimeFrame.Day,
                limit=_MIN_BARS,
            )
        except Exception as exc:
            logger.warning(
                "RegimeFilter: could not fetch SPY bars: %s — defaulting to NEUTRAL",
                exc,
            )
            return "NEUTRAL"

        if df.empty or len(df) < _SMA_PERIOD:
            logger.warning(
                "RegimeFilter: insufficient SPY data (%d bars, need %d) — NEUTRAL",
                len(df), _SMA_PERIOD,
            )
            return "NEUTRAL"

        try:
            close = df["close"]
            sma_200 = float(close.rolling(_SMA_PERIOD).mean().iloc[-1])
            latest_close = float(close.iloc[-1])

            momentum_positive = (
                float(close.iloc[-1]) > float(close.iloc[-_MOMENTUM_DAYS])
                if len(close) >= _MOMENTUM_DAYS
                else True
            )

            above_sma = latest_close > sma_200

            if above_sma and momentum_positive:
                regime = "BULL"
            elif not above_sma and not momentum_positive:
                regime = "BEAR"
            else:
                regime = "NEUTRAL"

            logger.info(
                "RegimeFilter: SPY=$%.2f SMA200=$%.2f | above=%s momentum_pos=%s → %s",
                latest_close, sma_200, above_sma, momentum_positive, regime,
            )
            return regime

        except Exception as exc:
            logger.warning(
                "RegimeFilter: computation failed: %s — defaulting to NEUTRAL", exc,
            )
            return "NEUTRAL"
