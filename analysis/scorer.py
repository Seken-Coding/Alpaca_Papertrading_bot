"""Enhanced multi-factor scoring engine (v2).

Key improvements over v1
------------------------
Market Regime Detection
  ADX + directional indices + BB width are used to classify the regime
  (strong/weak uptrend, ranging, strong/weak downtrend, volatile).
  Each regime gets a different weight vector so that trend indicators
  dominate in trending markets and oscillators dominate in ranging ones.

Volume Direction Awareness
  Relative volume (RVOL) is now directional: a 2× surge on an *up* day
  is accumulation (bullish); on a *down* day it is distribution (bearish).
  The old scorer gave both the same bullish score — a significant flaw.

RSI Divergence
  Bullish/bearish RSI divergence is the highest-conviction RSI signal and
  is now detected and weighted above raw RSI level scores.

Ichimoku Cloud
  Price position relative to the cloud, cloud colour (Span A vs B), and
  Tenkan/Kijun cross replace crude SMA checks for trend scoring.

EMA Ribbon
  A 0-100 alignment score across [9, 21, 50, 200] EMAs reflects the full
  trend stack, not just one MA cross.

Confluence Adjustment
  After weighted aggregation a bonus is added when 4-5 dimensions agree,
  and a penalty is applied when 2+ dimensions give conflicting signals.

Regime-aware BB Interpretation
  In an uptrend the lower band is a buy-dip opportunity; in a downtrend
  the upper band is a sell-the-bounce opportunity — not a neutral signal.

MACD Normalisation
  The histogram is divided by price to get a dimensionless %-of-price
  value, eliminating the scale-dependence of the old `hist * 100` hack.

Additional Risk Metrics in Output
  StockScore now exposes `risk_pct` (ATR as % of price) and `hv_20`
  (20-day annualised historical volatility) so callers can size positions.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from analysis import indicators as ind
from analysis.signals import Signal, crossover, crossunder

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    """Safely coerce *val* to float; return *default* on None / NaN."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _avg(scores: list, default: float = 50.0) -> float:
    """Mean of *scores*, clipped to [0, 100]; returns *default* if empty."""
    if not scores:
        return default
    return float(np.clip(np.mean(scores), 0, 100))


# ─────────────────────────────────────────────────────────────────────────────
# Market Regime
# ─────────────────────────────────────────────────────────────────────────────

class MarketRegime(Enum):
    STRONG_UPTREND   = "Strong Uptrend"
    WEAK_UPTREND     = "Weak Uptrend"
    RANGING          = "Ranging"
    WEAK_DOWNTREND   = "Weak Downtrend"
    STRONG_DOWNTREND = "Strong Downtrend"
    VOLATILE         = "Volatile"


def detect_regime(latest: pd.Series) -> MarketRegime:
    """Classify the current market regime from the most-recent indicator row.

    Priority:
      1. Very wide Bollinger Bands → Volatile (elevated uncertainty)
      2. ADX > 25 with directional bias → Trending (strong or weak)
      3. Otherwise → Ranging (oscillator-friendly)
    """
    adx      = _f(latest.get("adx"), 20.0)
    plus_di  = _f(latest.get("plus_di"), 25.0)
    minus_di = _f(latest.get("minus_di"), 25.0)
    bb_width = _f(latest.get("bb_width"), 0.05)

    if bb_width > 0.12:
        return MarketRegime.VOLATILE

    if adx > 25:
        if plus_di > minus_di:
            return MarketRegime.STRONG_UPTREND if adx > 35 else MarketRegime.WEAK_UPTREND
        else:
            return MarketRegime.STRONG_DOWNTREND if adx > 35 else MarketRegime.WEAK_DOWNTREND

    return MarketRegime.RANGING


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScoringWeights:
    """Relative importance of each scoring dimension (must sum to 1.0)."""
    trend:        float = 0.30
    momentum:     float = 0.25
    volume:       float = 0.20
    volatility:   float = 0.12
    price_action: float = 0.13

    def __post_init__(self):
        total = (
            self.trend + self.momentum + self.volume
            + self.volatility + self.price_action
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"ScoringWeights must sum to 1.0; got {total:.3f}")


# Weights tuned per regime — the dimension most *informative* in each
# regime receives the highest weight.
_REGIME_WEIGHTS: dict[MarketRegime, ScoringWeights] = {
    # In a strong uptrend the trend itself is the best predictor.
    MarketRegime.STRONG_UPTREND:   ScoringWeights(0.35, 0.20, 0.22, 0.10, 0.13),
    MarketRegime.WEAK_UPTREND:     ScoringWeights(0.28, 0.25, 0.20, 0.12, 0.15),
    # Oscillators (momentum) are far more informative in a ranging market.
    MarketRegime.RANGING:          ScoringWeights(0.12, 0.32, 0.18, 0.25, 0.13),
    MarketRegime.WEAK_DOWNTREND:   ScoringWeights(0.28, 0.25, 0.20, 0.12, 0.15),
    MarketRegime.STRONG_DOWNTREND: ScoringWeights(0.35, 0.20, 0.22, 0.10, 0.13),
    # In a volatile market, volatility structure and volume quality matter most.
    MarketRegime.VOLATILE:         ScoringWeights(0.15, 0.20, 0.22, 0.30, 0.13),
}


@dataclass
class ScoringThresholds:
    """Composite score thresholds used to map scores to signals."""
    buy_threshold:  float = 60.0
    sell_threshold: float = 40.0
    strong_buy:     float = 72.0
    strong_sell:    float = 28.0


# ─────────────────────────────────────────────────────────────────────────────
# Score result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StockScore:
    """Comprehensive multi-dimensional score for a single stock."""
    symbol:       str
    price:        float
    composite:    float    # 0-100 overall score
    trend:        float    # 0-100
    momentum:     float    # 0-100
    volume:       float    # 0-100
    volatility:   float    # 0-100
    price_action: float    # 0-100
    signal:       Signal
    confidence:   str      # "Strong" | "Moderate" | "Weak"
    regime:       str      # MarketRegime.value
    risk_pct:     float    # ATR as % of price (expected daily move)
    hv_20:        float    # 20-day annualised historical volatility (%)
    reasons:      list = field(default_factory=list)

    def __str__(self) -> str:
        arrow = {"BUY": "▲", "SELL": "▼", "HOLD": "—"}.get(self.signal.value, "?")
        return (
            f"{arrow} {self.signal.value:<4}  {self.symbol:<6}  "
            f"${self.price:>9.2f}  Score={self.composite:5.1f}  "
            f"[T={self.trend:.0f} M={self.momentum:.0f} "
            f"V={self.volume:.0f} Vola={self.volatility:.0f} PA={self.price_action:.0f}]  "
            f"Risk={self.risk_pct:.1f}%/day  HV={self.hv_20:.0f}%  "
            f"{self.regime}  [{self.confidence}]"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scoring Engine
# ─────────────────────────────────────────────────────────────────────────────

class ScoringEngine:
    """Regime-aware, confluence-adjusted multi-factor scoring engine.

    Usage
    -----
    engine = ScoringEngine()
    df = engine.prepare(raw_ohlcv_df)   # applies full indicator suite
    score = engine.score(df, "AAPL")
    print(score)
    """

    def __init__(
        self,
        weights: Optional[ScoringWeights] = None,
        thresholds: Optional[ScoringThresholds] = None,
        use_regime_weights: bool = True,
    ):
        self._default_weights = weights or ScoringWeights()
        self.t = thresholds or ScoringThresholds()
        self.use_regime_weights = use_regime_weights

    # ── Public API ───────────────────────────────────────────────────────

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the complete indicator suite to *df* and return it."""
        return ind.apply_all(df)

    def score(self, df: pd.DataFrame, symbol: str) -> StockScore:
        """Compute a composite score for the most recent bar in *df*.

        *df* should already have indicator columns (call ``prepare`` first,
        or pass a manually enriched DataFrame).
        """
        if len(df) < 60:
            return StockScore(
                symbol=symbol, price=0.0, composite=50.0,
                trend=50, momentum=50, volume=50, volatility=50, price_action=50,
                signal=Signal.HOLD, confidence="Weak",
                regime="Unknown", risk_pct=0.0, hv_20=0.0,
                reasons=["Insufficient data (need ≥60 bars)"],
            )

        latest  = df.iloc[-1]
        price   = _f(latest.get("close"), 0.0)
        reasons: list[str] = []

        # 1. Regime detection → adaptive weights
        regime = detect_regime(latest)
        w = (
            _REGIME_WEIGHTS.get(regime, self._default_weights)
            if self.use_regime_weights
            else self._default_weights
        )
        reasons.append(f"Regime: {regime.value}")

        # 2. Dimension scores
        trend_score = self._score_trend(df, latest, regime, reasons)
        mom_score   = self._score_momentum(df, latest, regime, reasons)
        vol_score   = self._score_volume(df, latest, regime, reasons)
        vola_score  = self._score_volatility(df, latest, regime, reasons)
        pa_score    = self._score_price_action(df, latest, regime, reasons)

        # 3. Weighted composite
        composite = (
            w.trend        * trend_score
            + w.momentum   * mom_score
            + w.volume     * vol_score
            + w.volatility * vola_score
            + w.price_action * pa_score
        )

        # 4. Confluence adjustment
        scores_map = {
            "trend": trend_score, "momentum": mom_score,
            "volume": vol_score, "volatility": vola_score,
            "price_action": pa_score,
        }
        composite = self._confluence_adjust(composite, scores_map, reasons)

        # 5. Risk metrics
        atr_val  = _f(latest.get("atr"), 0.0)
        risk_pct = (atr_val / price * 100) if price > 0 else 0.0
        hv_20    = _f(latest.get("hv_20"), 0.0)

        signal, confidence = self._classify(composite)

        return StockScore(
            symbol       = symbol,
            price        = round(price, 2),
            composite    = round(composite, 1),
            trend        = round(trend_score, 1),
            momentum     = round(mom_score, 1),
            volume       = round(vol_score, 1),
            volatility   = round(vola_score, 1),
            price_action = round(pa_score, 1),
            signal       = signal,
            confidence   = confidence,
            regime       = regime.value,
            risk_pct     = round(risk_pct, 2),
            hv_20        = round(hv_20, 1),
            reasons      = reasons,
        )

    # ── Dimension scorers (each returns 0-100) ───────────────────────────

    def _score_trend(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        regime: MarketRegime,
        reasons: list,
    ) -> float:
        scores: list[float] = []
        price = _f(latest.get("close"))

        # ── 1. Ichimoku Cloud ────────────────────────────────────────────
        cloud_top = _f(latest.get("ichi_cloud_top"), np.nan)
        cloud_bot = _f(latest.get("ichi_cloud_bottom"), np.nan)
        if not (np.isnan(cloud_top) or np.isnan(cloud_bot) or cloud_top == 0):
            cloud_bullish = (
                _f(latest.get("ichi_cloud_a")) >= _f(latest.get("ichi_cloud_b"))
            )
            if price > cloud_top:
                scores.append(88 if cloud_bullish else 72)
                reasons.append(
                    "Above Ichimoku cloud"
                    + (" (bullish cloud)" if cloud_bullish else " (bearish cloud)")
                )
            elif price < cloud_bot:
                scores.append(12 if not cloud_bullish else 28)
                reasons.append("Below Ichimoku cloud")
            else:
                scores.append(45)  # Inside cloud = uncertainty / transition

            # Tenkan / Kijun cross
            tenkan = _f(latest.get("ichi_tenkan"), price)
            kijun  = _f(latest.get("ichi_kijun"), price)
            if tenkan > kijun:
                scores.append(63)
            elif tenkan < kijun:
                scores.append(37)

        # ── 2. EMA Ribbon alignment ──────────────────────────────────────
        if "ema_ribbon_score" in latest:
            ribbon = _f(latest.get("ema_ribbon_score"), 50.0)
            scores.append(ribbon)
            if ribbon >= 90:
                reasons.append("Full bull EMA ribbon (9>21>50>200)")
            elif ribbon <= 10:
                reasons.append("Full bear EMA ribbon (9<21<50<200)")

        # ── 3. SMA stack (price vs 20/50/200) ───────────────────────────
        s20  = _f(latest.get("sma_20"))
        s50  = _f(latest.get("sma_50"))
        s200 = _f(latest.get("sma_200"))
        if s20 and s50 and s200:
            if price > s20 > s50 > s200:
                scores.append(92)
                reasons.append("Perfect bull SMA stack (Price > 20 > 50 > 200)")
            elif price > s50 > s200:
                scores.append(75)
            elif price > s200:
                scores.append(60)
            elif price < s20 < s50 < s200:
                scores.append(8)
                reasons.append("Perfect bear SMA stack (Price < 20 < 50 < 200)")
            elif price < s50 < s200:
                scores.append(25)
            elif price < s200:
                scores.append(40)
            else:
                scores.append(50)

        # ── 4. Linear regression slope ───────────────────────────────────
        slope_raw = latest.get("lr_slope_20")
        if slope_raw is not None:
            slope = _f(slope_raw)
            if not np.isnan(slope):
                # ±0.5 %/bar → ±40 pts around 50
                slope_score = float(np.clip(50 + slope * 80, 0, 100))
                scores.append(slope_score)
                if slope > 0.4:
                    reasons.append(f"Strong upward trend slope ({slope:.2f}%/bar)")
                elif slope < -0.4:
                    reasons.append(f"Strong downward trend slope ({slope:.2f}%/bar)")

        # ── 5. ADX with directional bias ─────────────────────────────────
        adx_val  = _f(latest.get("adx"), 20.0)
        plus_di  = _f(latest.get("plus_di"), 25.0)
        minus_di = _f(latest.get("minus_di"), 25.0)
        if adx_val > 15:
            direction_bias = plus_di - minus_di     # +ve = bullish
            # Blend neutral (50) toward the directional bias; weight by ADX
            raw = float(np.clip(50 + direction_bias * 1.2, 0, 100))
            strength = min(adx_val / 40.0, 1.0)
            adx_score = 50 + (raw - 50) * strength
            scores.append(float(np.clip(adx_score, 0, 100)))
            if adx_val > 30 and plus_di > minus_di:
                reasons.append(f"Uptrend confirmed (ADX={adx_val:.0f}, +DI={plus_di:.0f})")
            elif adx_val > 30 and plus_di < minus_di:
                reasons.append(f"Downtrend confirmed (ADX={adx_val:.0f}, -DI={minus_di:.0f})")

        # ── 6. SMA golden / death cross (event signal) ───────────────────
        if "sma_20" in df.columns and "sma_50" in df.columns:
            if crossover(df["sma_20"], df["sma_50"]).iloc[-1]:
                scores.append(90)
                reasons.append("Golden cross (SMA 20/50)")
            elif crossunder(df["sma_20"], df["sma_50"]).iloc[-1]:
                scores.append(10)
                reasons.append("Death cross (SMA 20/50)")

        return _avg(scores, 50.0)

    def _score_momentum(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        regime: MarketRegime,
        reasons: list,
    ) -> float:
        scores: list[float] = []
        price = _f(latest.get("close"), 1.0)

        # ── 1. RSI divergence (highest-priority momentum signal) ─────────
        rsi_div = int(_f(latest.get("rsi_divergence"), 0))
        if rsi_div > 0:
            scores.append(80)
            reasons.append("Bullish RSI divergence")
        elif rsi_div < 0:
            scores.append(20)
            reasons.append("Bearish RSI divergence")

        # ── 2. RSI level — regime-aware thresholds ───────────────────────
        rsi_val = _f(latest.get("rsi"), 50.0)
        uptrend   = regime in (MarketRegime.STRONG_UPTREND, MarketRegime.WEAK_UPTREND)
        downtrend = regime in (MarketRegime.STRONG_DOWNTREND, MarketRegime.WEAK_DOWNTREND)

        if uptrend:
            # In an uptrend RSI holds above 40; a dip to 40-50 = buy opportunity
            if 50 <= rsi_val <= 72:
                scores.append(70)
            elif 40 <= rsi_val < 50:
                scores.append(62)   # Healthy pullback
            elif rsi_val < 40:
                scores.append(74)   # Deep dip in uptrend = high-quality entry
                reasons.append(f"RSI dip in uptrend ({rsi_val:.0f}) — quality entry")
            elif 72 < rsi_val <= 82:
                scores.append(52)   # Overbought but trending can stay overbought
            else:
                scores.append(32)   # Extremely overbought
                reasons.append(f"RSI extremely overbought ({rsi_val:.0f})")
        elif downtrend:
            # In a downtrend RSI holds below 60; a rally to 50-60 = sell opportunity
            if 30 <= rsi_val <= 50:
                scores.append(30)
            elif rsi_val < 30:
                scores.append(58)   # Oversold in downtrend — bounce possible but risky
                reasons.append(f"RSI oversold in downtrend ({rsi_val:.0f}) — bounce risk")
            elif 50 < rsi_val <= 60:
                scores.append(22)   # Overbought in downtrend = sell
            elif rsi_val > 60:
                scores.append(15)
                reasons.append(f"RSI overbought in downtrend ({rsi_val:.0f})")
        else:
            # Ranging / volatile: classic mean-reversion thresholds
            if rsi_val < 30:
                scores.append(78)
                reasons.append(f"RSI oversold ({rsi_val:.0f})")
            elif rsi_val > 70:
                scores.append(22)
                reasons.append(f"RSI overbought ({rsi_val:.0f})")
            elif 40 <= rsi_val <= 60:
                scores.append(50)
            else:
                scores.append(float(np.clip(50 + (rsi_val - 50) * 0.5, 0, 100)))

        # ── 3. MACD — price-normalised histogram + crossover ─────────────
        if "macd_hist" in df.columns:
            hist = _f(latest.get("macd_hist"))
            # Normalise: express histogram as % of price to remove scale dependency
            hist_pct = hist / price * 100 if price > 0 else 0.0
            # ±0.1% of price → ±50 pts; clip to [10, 90] to avoid extremes
            hist_score = float(np.clip(50 + hist_pct * 500, 10, 90))
            scores.append(hist_score)

            # Histogram acceleration: two consecutive increasing/decreasing bars
            if len(df) >= 3:
                h1 = _f(df["macd_hist"].iloc[-2])
                h2 = _f(df["macd_hist"].iloc[-3])
                if hist > h1 > h2 and h1 < 0:
                    scores.append(76)
                    reasons.append("MACD histogram accelerating up from negative")
                elif hist < h1 < h2 and h1 > 0:
                    scores.append(24)
                    reasons.append("MACD histogram accelerating down from positive")

            if "macd_signal" in df.columns:
                if crossover(df["macd"], df["macd_signal"]).iloc[-1]:
                    scores.append(83)
                    reasons.append("MACD bullish crossover")
                elif crossunder(df["macd"], df["macd_signal"]).iloc[-1]:
                    scores.append(17)
                    reasons.append("MACD bearish crossover")

        # ── 4. Stochastic — regime-aware interpretation ──────────────────
        stk = _f(latest.get("stoch_k"), 50.0)
        std = _f(latest.get("stoch_d"), 50.0)
        if stk < 20 and std < 20:
            # Oversold; less bullish if we're in a downtrend
            scores.append(68 if not downtrend else 52)
        elif stk > 80 and std > 80:
            # Overbought; less bearish if we're in an uptrend
            scores.append(32 if not uptrend else 48)
        elif stk > std:
            scores.append(60)
        elif stk < std:
            scores.append(40)
        else:
            scores.append(50)

        # ── 5. Williams %R (-100 to 0 → maps linearly to 0-100) ─────────
        wr = _f(latest.get("williams_r"), -50.0)
        scores.append(float(np.clip(wr + 100, 0, 100)))

        # ── 6. Rate of change (5-day and 12-day) ────────────────────────
        for key in ("roc_5", "roc_12"):
            roc_val = latest.get(key)
            if roc_val is not None:
                scores.append(float(np.clip(50 + _f(roc_val) * 2.5, 0, 100)))

        return _avg(scores, 50.0)

    def _score_volume(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        regime: MarketRegime,
        reasons: list,
    ) -> float:
        scores: list[float] = []
        price      = _f(latest.get("close"), 1.0)
        prev_close = _f(df["close"].iloc[-2], price) if len(df) >= 2 else price
        up_day     = price >= prev_close   # Is today's bar an up day?

        # ── 1. Directional RVOL — volume surge must be contextualised ────
        rvol = _f(latest.get("rvol"), 1.0)
        if rvol > 2.0:
            if up_day:
                scores.append(88)
                reasons.append(f"Strong accumulation (RVOL {rvol:.1f}× on up day)")
            else:
                scores.append(12)
                reasons.append(f"Strong distribution (RVOL {rvol:.1f}× on down day)")
        elif rvol > 1.5:
            scores.append(68 if up_day else 32)
        elif rvol > 1.0:
            scores.append(57 if up_day else 43)
        elif rvol > 0.7:
            scores.append(50)
        else:
            scores.append(42)   # Low volume = low conviction regardless of direction

        # ── 2. Volume direction (up-day vs down-day volume over 14 bars) ─
        vd = _f(latest.get("vol_direction"), 1.0)
        if vd > 2.0:
            scores.append(82)
            reasons.append(f"Buying volume dominance ({vd:.1f}×)")
        elif vd > 1.4:
            scores.append(65)
        elif vd < 0.5:
            scores.append(18)
            reasons.append("Selling volume dominance")
        elif vd < 0.71:
            scores.append(35)
        else:
            scores.append(50)

        # ── 3. Chaikin A/D slope (10-bar trend of smart money flow) ──────
        if "chaikin_ad" in df.columns and len(df) >= 10:
            ad_now   = _f(df["chaikin_ad"].iloc[-1])
            ad_prior = _f(df["chaikin_ad"].iloc[-10])
            ad_slope = ad_now - ad_prior
            if ad_slope > 0:
                scores.append(65)
                if abs(ad_prior) > 0 and ad_slope / abs(ad_prior) > 0.05:
                    reasons.append("Significant accumulation (Chaikin A/D rising)")
            else:
                scores.append(35)
                if abs(ad_prior) > 0 and ad_slope / abs(ad_prior) < -0.05:
                    reasons.append("Significant distribution (Chaikin A/D falling)")

        # ── 4. OBV vs its 20-period MA ───────────────────────────────────
        if "obv" in df.columns and len(df) >= 20:
            obv_ma  = df["obv"].rolling(20).mean().iloc[-1]
            obv_now = _f(latest.get("obv"))
            if obv_ma != 0:
                deviation_pct = (obv_now - obv_ma) / abs(obv_ma) * 100
                scores.append(float(np.clip(50 + deviation_pct * 2, 0, 100)))

        # ── 5. MFI (volume-weighted RSI) ─────────────────────────────────
        mfi_val = _f(latest.get("mfi"), 50.0)
        if mfi_val > 80:
            scores.append(22)   # Money flowing out imminently
        elif mfi_val > 60:
            scores.append(62)
        elif mfi_val < 20:
            scores.append(78)
            reasons.append(f"MFI oversold ({mfi_val:.0f}) — potential accumulation")
        elif mfi_val < 40:
            scores.append(38)
        else:
            scores.append(50)

        return _avg(scores, 50.0)

    def _score_volatility(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        regime: MarketRegime,
        reasons: list,
    ) -> float:
        scores: list[float] = []
        price    = _f(latest.get("close"), 1.0)
        uptrend  = regime in (MarketRegime.STRONG_UPTREND, MarketRegime.WEAK_UPTREND)
        downtrend = regime in (MarketRegime.STRONG_DOWNTREND, MarketRegime.WEAK_DOWNTREND)

        # ── 1. BB position — interpreted relative to the regime ──────────
        bb_low = _f(latest.get("bb_lower"))
        bb_up  = _f(latest.get("bb_upper"))
        band_range = bb_up - bb_low
        if band_range > 0:
            pos = (price - bb_low) / band_range   # 0 = lower band, 1 = upper band

            if uptrend:
                # Lower band = quality buy-the-dip; upper band = momentum continuation
                if pos < 0.15:
                    scores.append(80)
                    reasons.append("BB lower band touch in uptrend — buy-the-dip")
                elif pos > 0.85:
                    scores.append(65)   # Healthy momentum
                else:
                    scores.append(55 + (pos - 0.5) * 20)
            elif downtrend:
                # Upper band = sell-the-bounce; lower band = oversold but trend is down
                if pos > 0.85:
                    scores.append(18)
                    reasons.append("BB upper band touch in downtrend — sell-the-bounce")
                elif pos < 0.15:
                    scores.append(40)   # Oversold but don't fight the trend
                else:
                    scores.append(45 + (pos - 0.5) * 15)
            else:
                # Ranging / volatile: classic mean-reversion
                if pos < 0.10:
                    scores.append(82)
                    reasons.append("Price at lower Bollinger Band")
                elif pos > 0.90:
                    scores.append(18)
                    reasons.append("Price at upper Bollinger Band")
                elif pos < 0.25:
                    scores.append(65)
                elif pos > 0.75:
                    scores.append(35)
                else:
                    scores.append(50)

        # ── 2. BB / KC Squeeze — coiling before an expansion ─────────────
        squeeze = bool(latest.get("bb_squeeze", False))
        if squeeze:
            scores.append(55)   # Directional neutral but elevated potential energy
            reasons.append("BB/KC squeeze — high-probability breakout setup")

        # ── 3. Historical volatility — risk environment ───────────────────
        hv = _f(latest.get("hv_20"), 20.0)
        if hv < 15:
            scores.append(70)   # Very low vol = calm, predictable environment
        elif hv < 25:
            scores.append(60)
        elif hv < 40:
            scores.append(45)
        elif hv < 60:
            scores.append(35)
        else:
            scores.append(20)   # Very high vol = unfavourable risk environment
            reasons.append(f"Elevated historical volatility ({hv:.0f}%)")

        # ── 4. CCI ───────────────────────────────────────────────────────
        cci_val = _f(latest.get("cci"), 0.0)
        if cci_val > 200:
            scores.append(18)
        elif cci_val > 100:
            scores.append(35)
        elif cci_val < -200:
            scores.append(82)
        elif cci_val < -100:
            scores.append(65)
        else:
            scores.append(float(np.clip(50 + cci_val / 3.0, 20, 80)))

        # ── 5. ATR contraction vs its 20-period mean ──────────────────────
        if "atr" in df.columns and len(df) >= 20:
            atr_ma  = df["atr"].rolling(20).mean().iloc[-1]
            atr_now = _f(latest.get("atr"))
            if atr_ma > 0:
                ratio = atr_now / atr_ma
                if ratio < 0.70:
                    scores.append(62)
                    reasons.append("ATR contraction — potential breakout setting up")
                elif ratio > 1.60:
                    scores.append(38)   # Expanded volatility = elevated risk

        return _avg(scores, 50.0)

    def _score_price_action(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        regime: MarketRegime,
        reasons: list,
    ) -> float:
        scores: list[float] = []
        price    = _f(latest.get("close"), 1.0)
        uptrend  = regime in (MarketRegime.STRONG_UPTREND, MarketRegime.WEAK_UPTREND)
        downtrend = regime in (MarketRegime.STRONG_DOWNTREND, MarketRegime.WEAK_DOWNTREND)

        # ── 1. Donchian Channel breakout (20-day) ────────────────────────
        if "dc_upper_20" in df.columns and len(df) >= 2:
            dc_high = _f(df["dc_upper_20"].iloc[-2])   # Previous bar's channel (no look-ahead)
            dc_low  = _f(df["dc_lower_20"].iloc[-2])
            dc_range = dc_high - dc_low
            if dc_range > 0:
                if price > dc_high:
                    scores.append(88)
                    reasons.append("20-day Donchian breakout (new high)")
                elif price < dc_low:
                    scores.append(12)
                    reasons.append("20-day Donchian breakdown (new low)")
                else:
                    pos = (price - dc_low) / dc_range
                    scores.append(float(np.clip(40 + pos * 20, 0, 100)))

        # ── 2. 52-week position (proximity to annual high/low) ───────────
        history_len = min(len(df), 252)
        if history_len >= 40:
            high_n = df["high"].iloc[-history_len:].max()
            low_n  = df["low"].iloc[-history_len:].min()
            range_n = high_n - low_n
            if range_n > 0:
                pos_n = (price - low_n) / range_n
                if pos_n > 0.90:
                    scores.append(80)
                    pct_label = "52-week" if history_len >= 252 else f"{history_len//5}-week"
                    reasons.append(f"Near {pct_label} high ({pos_n:.0%} of range)")
                elif pos_n < 0.10:
                    scores.append(20)
                    pct_label = "52-week" if history_len >= 252 else f"{history_len//5}-week"
                    reasons.append(f"Near {pct_label} low ({pos_n:.0%} of range)")
                else:
                    scores.append(float(np.clip(40 + pos_n * 20, 0, 100)))

        # ── 3. Consecutive close streak ──────────────────────────────────
        streak_val = int(_f(latest.get("streak"), 0))
        if streak_val >= 4:
            # Long winning streak is more bullish when it aligns with the regime
            scores.append(75 if uptrend else 62)
            reasons.append(f"{streak_val}-day winning streak")
        elif streak_val >= 2:
            scores.append(60)
        elif streak_val <= -4:
            scores.append(25 if downtrend else 38)
            reasons.append(f"{abs(streak_val)}-day losing streak")
        elif streak_val <= -2:
            scores.append(40)
        else:
            scores.append(float(np.clip(50 + streak_val * 5, 0, 100)))

        # ── 4. 5-day rate of change (short-term price momentum) ──────────
        roc5 = latest.get("roc_5")
        if roc5 is not None:
            scores.append(float(np.clip(50 + _f(roc5) * 3.0, 0, 100)))

        # ── 5. Gap analysis ───────────────────────────────────────────────
        gap_val = latest.get("gap_pct")
        if gap_val is not None:
            g = _f(gap_val)
            if g > 3.0:
                scores.append(80)
                reasons.append(f"Gap up {g:.1f}%")
            elif g > 1.0:
                scores.append(62)
            elif g < -3.0:
                scores.append(20)
                reasons.append(f"Gap down {g:.1f}%")
            elif g < -1.0:
                scores.append(38)
            else:
                scores.append(float(np.clip(50 + g * 5, 0, 100)))

        return _avg(scores, 50.0)

    # ── Post-processing helpers ───────────────────────────────────────────

    @staticmethod
    def _confluence_adjust(
        composite: float, scores_map: dict, reasons: list
    ) -> float:
        """Apply a bonus when all dimensions agree; penalty when they conflict.

        Rationale: a composite score of 65 built from five 65s is far more
        reliable than one built from a 95 and four 58s.  This captures the
        difference.
        """
        bull_dims = sum(1 for s in scores_map.values() if s >= 60)
        bear_dims = sum(1 for s in scores_map.values() if s <= 40)

        adj = 0.0
        if bull_dims == 5:
            adj = +9.0
            reasons.append("Maximum confluence — all 5 dimensions bullish")
        elif bull_dims == 4:
            adj = +4.5
            reasons.append(f"High confluence ({bull_dims}/5 dimensions bullish)")
        elif bear_dims == 5:
            adj = -9.0
            reasons.append("Maximum confluence — all 5 dimensions bearish")
        elif bear_dims == 4:
            adj = -4.5
            reasons.append(f"High confluence ({bear_dims}/5 dimensions bearish)")

        # Conflict penalty: two or more opposing dimensions reduce conviction
        if bull_dims >= 2 and bear_dims >= 2:
            adj -= 5.0
            reasons.append("Mixed signals — conviction reduced")

        return float(np.clip(composite + adj, 0, 100))

    def _classify(self, composite: float) -> tuple:
        """Map composite score to (Signal, confidence) tuple."""
        if composite >= self.t.strong_buy:
            return Signal.BUY, "Strong"
        elif composite >= self.t.buy_threshold:
            return Signal.BUY, "Moderate"
        elif composite <= self.t.strong_sell:
            return Signal.SELL, "Strong"
        elif composite <= self.t.sell_threshold:
            return Signal.SELL, "Moderate"
        else:
            return Signal.HOLD, "Weak"
