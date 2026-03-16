"""CEST Strategy parameters — all magic numbers in one place.

Composite Edge Systematic Trader configuration.
No magic numbers should appear in strategy code; everything references this module.
"""

from dataclasses import dataclass, field
from typing import Any

# --- Broker ---
BROKER = "alpaca"  # "alpaca" or "ib"
PAPER_TRADING = True

# --- Universe ---
CORE_ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE",
    "XLK", "XLV", "XLI", "GLD", "SLV", "TLT",
]
DYNAMIC_UNIVERSE_SIZE = 50
MIN_MARKET_CAP = 5_000_000_000
MIN_DOLLAR_VOLUME = 50_000_000
MIN_PRICE = 10.0
ATR_PCT_MIN = 0.5
ATR_PCT_MAX = 8.0

# --- Indicators ---
EMA_FAST = 10
EMA_SLOW = 21
EMA_REGIME = 200
RSI_PERIOD = 14
RSI_SHORT_PERIOD = 3
ADX_PERIOD = 14
ATR_PERIOD = 20
DONCHIAN_PERIOD = 20
BB_PERIOD = 20
BB_STD = 2.0
VOLUME_SMA_PERIOD = 20
VOL_LOOKBACK = 252
CORRELATION_LOOKBACK = 60

# --- Regime Thresholds ---
EMA_SLOPE_THRESHOLD = 0.05       # %/bar
ADX_TREND_THRESHOLD = 25
ADX_RANGE_THRESHOLD = 20
VOL_PERCENTILE_HIGH = 90
VOL_PERCENTILE_CRISIS = 95

# --- Entry ---
VOLUME_BREAKOUT_MULTIPLIER = 1.5
RSI_MR_OVERSOLD = 15
RSI_MR_OVERBOUGHT = 85
RSI_TREND_LOW = 50
RSI_TREND_HIGH = 80
MR_DISTANCE_FROM_MEAN_PCT = 2.0
BB_WIDTH_PERCENTILE = 25
MIN_CONFLUENCE_SCORE = 5

# --- Exit ---
TREND_STOP_ATR_MULT = 2.0
MR_STOP_ATR_MULT = 1.5
TRAILING_STOP_ATR_MULT = 3.0
TREND_PARTIAL_PROFIT_R = 3.0
TREND_PARTIAL_SIZE = 0.50        # close 50% at target
MR_TARGET_R = 1.5
TREND_TIME_STOP_BARS = 10
MR_TIME_STOP_BARS = 5
BREAKEVEN_TRIGGER_R = 1.5
MR_RSI_EXIT_LONG = 70
MR_RSI_EXIT_SHORT = 30

# --- Position Sizing ---
RISK_PER_TRADE = 0.01            # 1%
MAX_RISK_PER_TRADE = 0.02        # 2% hard cap

# --- Portfolio Risk ---
MAX_POSITIONS = 10
MAX_SAME_DIRECTION = 6
MAX_SECTOR_POSITIONS = 3
CORRELATION_THRESHOLD = 0.70
PORTFOLIO_CORR_LIMIT = 0.50

# --- Drawdown ---
DD_WARNING = 5
DD_REDUCE_50 = 10
DD_REDUCE_75 = 15
DD_HALT = 20
DD_HALT_DAYS = 20               # Trading days to pause

# --- Equity Curve ---
EQUITY_SMA_PERIOD = 50           # trades
EQUITY_HALT_SMA_PERIOD = 100     # trades

# --- Darvas Box (Nicolas Darvas) ---
DARVAS_LOOKBACK = 60            # bars to scan for boxes
DARVAS_CONFIRMATION_BARS = 3    # bars to confirm ceiling/floor

# --- Pyramiding (Jesse Livermore) ---
PYRAMIDING_ENABLED = True
MAX_PYRAMID_ADDS = 2
PYRAMID_SIZE_FRACTIONS = [0.50, 0.30]  # size per level as fraction of original
PYRAMID_R_THRESHOLD = 1.0              # must be +1R per level before adding

# --- SPY Macro Regime (Paul Tudor Jones) ---
SPY_MACRO_ENABLED = True
SPY_SMA_LONG = 200
SPY_SMA_SHORT = 50

# --- Gap Protection ---
GAP_PROTECTION_ENABLED = True
GAP_ATR_MULTIPLIER = 5.0        # gap > 5×ATR past stop = blown stop
MAX_LOSS_R_MULTIPLE = 3.0       # cap single-position loss at 3R
PORTFOLIO_GAP_LOSS_PCT = 5.0    # emergency if portfolio down 5% at open

# --- Scheduling ---
DAILY_RUN_TIME = "15:55"         # ET, 5 min before close
WEEKLY_SCAN_DAY = "Monday"

# --- Data ---
TRADE_LOG_PATH = "data/trade_log.csv"
STATE_PATH = "data/bot_state.json"
LOG_PATH = "logs/cest_bot.log"

# --- Sector Map ---
SECTOR_MAP = {
    "SPY": "INDEX", "QQQ": "INDEX", "IWM": "INDEX", "DIA": "INDEX",
    "XLF": "FINANCIALS", "XLE": "ENERGY", "XLK": "TECHNOLOGY",
    "XLV": "HEALTHCARE", "XLI": "INDUSTRIALS",
    "GLD": "COMMODITIES", "SLV": "COMMODITIES", "TLT": "BONDS",
    # Dynamic stocks will use a default sector lookup
}

# Default sector for symbols not in SECTOR_MAP
DEFAULT_SECTOR = "UNKNOWN"


@dataclass
class CestConfig:
    """Runtime CEST config — mirrors module-level constants but can be overridden.

    Use ``CestConfig.from_overrides({"RISK_PER_TRADE": 0.005})`` to create
    a variant with selected parameters changed.  The defaults match the
    module-level constants above.
    """

    BROKER: str = BROKER
    PAPER_TRADING: bool = PAPER_TRADING

    # Universe
    CORE_ETFS: list = field(default_factory=lambda: list(CORE_ETFS))
    DYNAMIC_UNIVERSE_SIZE: int = DYNAMIC_UNIVERSE_SIZE
    MIN_MARKET_CAP: int = MIN_MARKET_CAP
    MIN_DOLLAR_VOLUME: int = MIN_DOLLAR_VOLUME
    MIN_PRICE: float = MIN_PRICE
    ATR_PCT_MIN: float = ATR_PCT_MIN
    ATR_PCT_MAX: float = ATR_PCT_MAX

    # Indicators
    EMA_FAST: int = EMA_FAST
    EMA_SLOW: int = EMA_SLOW
    EMA_REGIME: int = EMA_REGIME
    RSI_PERIOD: int = RSI_PERIOD
    RSI_SHORT_PERIOD: int = RSI_SHORT_PERIOD
    ADX_PERIOD: int = ADX_PERIOD
    ATR_PERIOD: int = ATR_PERIOD
    DONCHIAN_PERIOD: int = DONCHIAN_PERIOD
    BB_PERIOD: int = BB_PERIOD
    BB_STD: float = BB_STD
    VOLUME_SMA_PERIOD: int = VOLUME_SMA_PERIOD
    VOL_LOOKBACK: int = VOL_LOOKBACK
    CORRELATION_LOOKBACK: int = CORRELATION_LOOKBACK

    # Regime
    EMA_SLOPE_THRESHOLD: float = EMA_SLOPE_THRESHOLD
    ADX_TREND_THRESHOLD: int = ADX_TREND_THRESHOLD
    ADX_RANGE_THRESHOLD: int = ADX_RANGE_THRESHOLD
    VOL_PERCENTILE_HIGH: int = VOL_PERCENTILE_HIGH
    VOL_PERCENTILE_CRISIS: int = VOL_PERCENTILE_CRISIS

    # Entry
    VOLUME_BREAKOUT_MULTIPLIER: float = VOLUME_BREAKOUT_MULTIPLIER
    RSI_MR_OVERSOLD: int = RSI_MR_OVERSOLD
    RSI_MR_OVERBOUGHT: int = RSI_MR_OVERBOUGHT
    RSI_TREND_LOW: int = RSI_TREND_LOW
    RSI_TREND_HIGH: int = RSI_TREND_HIGH
    MR_DISTANCE_FROM_MEAN_PCT: float = MR_DISTANCE_FROM_MEAN_PCT
    BB_WIDTH_PERCENTILE: int = BB_WIDTH_PERCENTILE
    MIN_CONFLUENCE_SCORE: int = MIN_CONFLUENCE_SCORE

    # Exit
    TREND_STOP_ATR_MULT: float = TREND_STOP_ATR_MULT
    MR_STOP_ATR_MULT: float = MR_STOP_ATR_MULT
    TRAILING_STOP_ATR_MULT: float = TRAILING_STOP_ATR_MULT
    TREND_PARTIAL_PROFIT_R: float = TREND_PARTIAL_PROFIT_R
    TREND_PARTIAL_SIZE: float = TREND_PARTIAL_SIZE
    MR_TARGET_R: float = MR_TARGET_R
    TREND_TIME_STOP_BARS: int = TREND_TIME_STOP_BARS
    MR_TIME_STOP_BARS: int = MR_TIME_STOP_BARS
    BREAKEVEN_TRIGGER_R: float = BREAKEVEN_TRIGGER_R
    MR_RSI_EXIT_LONG: int = MR_RSI_EXIT_LONG
    MR_RSI_EXIT_SHORT: int = MR_RSI_EXIT_SHORT

    # Position Sizing
    RISK_PER_TRADE: float = RISK_PER_TRADE
    MAX_RISK_PER_TRADE: float = MAX_RISK_PER_TRADE

    # Portfolio Risk
    MAX_POSITIONS: int = MAX_POSITIONS
    MAX_SAME_DIRECTION: int = MAX_SAME_DIRECTION
    MAX_SECTOR_POSITIONS: int = MAX_SECTOR_POSITIONS
    CORRELATION_THRESHOLD: float = CORRELATION_THRESHOLD
    PORTFOLIO_CORR_LIMIT: float = PORTFOLIO_CORR_LIMIT

    # Drawdown
    DD_WARNING: int = DD_WARNING
    DD_REDUCE_50: int = DD_REDUCE_50
    DD_REDUCE_75: int = DD_REDUCE_75
    DD_HALT: int = DD_HALT
    DD_HALT_DAYS: int = DD_HALT_DAYS

    # Equity Curve
    EQUITY_SMA_PERIOD: int = EQUITY_SMA_PERIOD
    EQUITY_HALT_SMA_PERIOD: int = EQUITY_HALT_SMA_PERIOD

    # Darvas Box
    DARVAS_LOOKBACK: int = DARVAS_LOOKBACK
    DARVAS_CONFIRMATION_BARS: int = DARVAS_CONFIRMATION_BARS

    # Pyramiding
    PYRAMIDING_ENABLED: bool = PYRAMIDING_ENABLED
    MAX_PYRAMID_ADDS: int = MAX_PYRAMID_ADDS
    PYRAMID_SIZE_FRACTIONS: list = field(default_factory=lambda: list(PYRAMID_SIZE_FRACTIONS))
    PYRAMID_R_THRESHOLD: float = PYRAMID_R_THRESHOLD

    # SPY Macro
    SPY_MACRO_ENABLED: bool = SPY_MACRO_ENABLED
    SPY_SMA_LONG: int = SPY_SMA_LONG
    SPY_SMA_SHORT: int = SPY_SMA_SHORT

    # Gap Protection
    GAP_PROTECTION_ENABLED: bool = GAP_PROTECTION_ENABLED
    GAP_ATR_MULTIPLIER: float = GAP_ATR_MULTIPLIER
    MAX_LOSS_R_MULTIPLE: float = MAX_LOSS_R_MULTIPLE
    PORTFOLIO_GAP_LOSS_PCT: float = PORTFOLIO_GAP_LOSS_PCT

    # Scheduling
    DAILY_RUN_TIME: str = DAILY_RUN_TIME
    WEEKLY_SCAN_DAY: str = WEEKLY_SCAN_DAY

    # Data paths
    TRADE_LOG_PATH: str = TRADE_LOG_PATH
    STATE_PATH: str = STATE_PATH
    LOG_PATH: str = LOG_PATH

    # Sector Map
    SECTOR_MAP: dict = field(default_factory=lambda: dict(SECTOR_MAP))
    DEFAULT_SECTOR: str = DEFAULT_SECTOR

    @classmethod
    def from_overrides(cls, overrides: dict[str, Any]) -> "CestConfig":
        """Create a CestConfig with selected parameters changed."""
        import dataclasses
        import logging
        _logger = logging.getLogger(__name__)
        field_names = {f.name for f in dataclasses.fields(cls)}
        valid = {}
        for k, v in overrides.items():
            if k in field_names:
                valid[k] = v
            else:
                _logger.warning(
                    "CestConfig.from_overrides: unknown key '%s' ignored "
                    "(not a valid CestConfig field)", k,
                )
        return cls(**valid)
