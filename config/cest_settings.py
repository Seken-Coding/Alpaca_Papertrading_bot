"""CEST Strategy parameters — all magic numbers in one place.

Composite Edge Systematic Trader configuration.
No magic numbers should appear in strategy code; everything references this module.
"""

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
