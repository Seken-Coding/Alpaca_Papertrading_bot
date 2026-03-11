# Master Trader Strategy Analysis & Bot Implementation Plan

## PHASE 1 — Study the Masters

### Trader-by-Trader Analysis

| Trader | Core Strategy | Entry Logic | Exit Logic | Risk Management | Psychological Edge | Regime Awareness |
|--------|--------------|-------------|------------|-----------------|-------------------|-----------------|
| **Ed Seykota** | Trend-following | MA crossovers (EMA-10/21), breakout filters, price > 200 EMA | Trailing stops (3×ATR Chandelier), ride winners | 1-2% risk per trade, never risk more than you can lose | "The trend is your friend" — let profits run, cut losses fast | Uses ADX + EMA slope to confirm trend strength |
| **Paul Tudor Jones** | Macro/volatility | Volatility expansion + market structure (higher lows), 200-day MA filter | Aggressive trailing, "first loss is best loss" | 2:1 min R:R, reduce size after losses | Contrarian at extremes, disciplined at all other times | 200-day SMA as bull/bear regime divider |
| **Stanley Druckenmiller** | Concentrated conviction | Asymmetric setups: huge potential reward, small defined risk | Hold winners until thesis breaks, cut losers at -1R | Scale position size with conviction (0.75×–1.5×) | "It's not whether you're right or wrong, it's how much you make when you're right" | Shifts between aggressive (trending) and defensive (ranging) |
| **Jim Simons** | Statistical arbitrage | Mean-reversion on short timeframes, pattern recognition, correlation filters | Fixed time exits, RSI normalization targets | Massive diversification, low correlation between positions, 0.5% risk per trade | Pure quantitative — removes all emotion | Regime-adaptive: different models for trending vs mean-reverting |
| **Richard Dennis** | Systematic breakout | Donchian 20-bar breakout, price > highest high | 10-bar Donchian low trailing stop, 2×ATR initial stop | 2% risk per trade, max 12% portfolio heat | Rules-based removes emotion, "trading CAN be taught" | Uses ATR percentile to filter false breakouts in low-vol regimes |
| **Mark Minervini** | SEPA momentum | VCP (Volatility Contraction Pattern), price in "stage 2" uptrend | Sell at -7% from entry, trail at 3×ATR after 1.5R profit | Max 1% risk per trade, concentrated in best setups | Only trade when conditions are perfect — "do nothing" is a position | Requires price above 200-SMA (stage 2) — refuses stage 3/4 |
| **Linda Raschke** | Short-term MR/momentum | RSI(3) < 15 oversold, ADX < 20, BB squeeze for mean-reversion | RSI(3) > 70 exit (MR), fixed 5-bar time stop | 1% risk, tight stops, high frequency | Pattern recognition from 30+ years of screen time | ADX < 20 for MR setups, ADX > 25 for momentum setups |
| **Larry Williams** | Swing/sentiment | Williams %R extremes, COT data showing commercial hedger positioning | Williams %R normalization, seasonal cycle end | 3-5% max risk per swing, scale down after drawdowns | Use sentiment data others ignore (COT, put/call ratios) | Seasonal patterns + sentiment extremes define regime |
| **Jesse Livermore** | Tape reading/pyramiding | Buy at new highs on volume, add to winners at higher pivot points | Never let a big profit turn into a loss — breakeven stop at +1R | Pyramid in: 50% initial, +30%, +20% at higher prices | "It is the big swing that makes the big money" — patience | Wait for "pivotal points" (key breakout levels) |
| **Nicolas Darvas** | Box breakout | Price consolidates in a "box" (defined high/low), buy on breakout above box top | Stop-loss below box bottom, trail using new boxes | Only risk capital you can afford to lose, 1-2% per trade | "I was right because I was wrong so many times" — accept losses | Only trades in bull markets (macro filter) |

---

## PHASE 2 — Common Principles (Across 3+ Traders)

### Universal Entry Filters
1. **Trend alignment** (Seykota, Jones, Dennis, Minervini, Darvas, Livermore) — Price must be above a long-term MA (200 EMA/SMA) for longs
2. **Volume confirmation** (Dennis, Minervini, Livermore, Darvas) — Breakout on above-average volume (>1.5× 20-day avg)
3. **Volatility contraction before expansion** (Minervini, Darvas, Raschke, Dennis) — Low BB width or VCP before breakout
4. **Momentum confirmation** (Seykota, Jones, Raschke) — RSI in favorable zone, not extreme overbought
5. **Confluence scoring** (Simons, Druckenmiller, Raschke) — Multiple independent signals must agree

### Universal Exit Rules
1. **ATR-based stops** (Seykota, Dennis, Raschke, Minervini) — Stop = Entry ± (1.5-2.0 × ATR)
2. **Breakeven rule** (Livermore, Minervini, Seykota) — Move stop to entry after +1.0-1.5R
3. **Trailing stop** (Seykota, Dennis, Minervini) — Chandelier: highest close - 3×ATR
4. **Time-based exit** (Simons, Raschke, Williams) — Exit if no 1R move within 5-10 bars
5. **Partial profit** (Livermore, Druckenmiller) — Take 50% at 3R, let rest ride

### Universal Risk Rules
1. **Fixed-fractional sizing** (All) — Risk 1-2% of equity per trade
2. **Max portfolio heat** (Dennis, Simons) — Total open risk < 12-15% of equity
3. **Drawdown circuit breakers** (Jones, Druckenmiller, Dennis) — Reduce size at 5%/10%/15% DD, halt at 20%
4. **Correlation limits** (Simons, Dennis) — Max 0.70 correlation between any two positions
5. **Conviction scaling** (Druckenmiller, Livermore) — Size proportional to setup quality

### Regime Detection
1. **EMA-200 slope** (Jones, Seykota, Minervini) — Bull if positive, bear if negative
2. **ADX threshold** (Raschke, Seykota) — Trending > 25, ranging < 20
3. **ATR percentile** (Dennis, Simons) — High-vol > 90th pctile, crisis > 95th
4. **SPY macro overlay** (Jones, Darvas, Livermore) — Only trade long if SPY > 200-SMA

### Psychological Rules
1. **Rules override feelings** (Dennis, Seykota, Simons) — Execute the system, no discretion
2. **Do nothing is a position** (Minervini, Livermore, Williams) — No signal = no trade
3. **Equity curve filter** (Seykota, Jones) — If equity < its own SMA, reduce size
4. **Journal every trade** (All) — Audit trail enables learning

---

## PHASE 3 — Bot Strategy Design

### What This Repo Already Implements

| Component | Status | Source Trader(s) |
|-----------|--------|-----------------|
| EMA/SMA moving averages | ✅ Full | Seykota |
| Donchian breakout entries | ✅ Full | Dennis |
| VCP pattern detection | ✅ Full | Minervini |
| RSI(3) mean-reversion | ✅ Full | Raschke, Simons |
| 5-regime classification | ✅ Full | Jones, Raschke |
| Confluence scoring | ✅ Full | Simons, Druckenmiller |
| ATR-based stops | ✅ Full | Seykota, Dennis |
| Chandelier trailing stop | ✅ Full | Seykota |
| Breakeven rule | ✅ Full | Livermore, Minervini |
| Partial profit at 3R | ✅ Full | Livermore, Druckenmiller |
| Time-based exits | ✅ Full | Simons, Raschke |
| Fixed-fractional sizing | ✅ Full | All |
| Conviction scaling | ✅ Full | Druckenmiller |
| Drawdown circuit breakers | ✅ Full | Jones, Dennis |
| Correlation filter | ✅ Full | Simons |
| Equity curve filter | ✅ Full | Seykota, Jones |
| Williams %R indicator | ✅ Exists | Williams (unused in entries) |

### What's Being Added (This PR)

| Component | Gap | Source Trader(s) |
|-----------|-----|-----------------|
| **Darvas Box breakout** | New pattern | Nicolas Darvas |
| **Pyramiding/add-to-winners** | Only partial exits existed | Jesse Livermore |
| **SPY macro regime overlay** | Per-symbol only, no market-wide check | Paul Tudor Jones, Darvas |
| **Gap risk protection** | No overnight gap handling | Black swan mitigation |
| **Backtesting engine** | No way to validate strategy | All (validation is universal) |

---

## PHASE 4 — Pseudocode Logic

```
function onNewCandle(candle):
    regime = detectRegime(data)                  # 5-state: TREND_UP/DOWN, RANGE, HIGH_VOL, CRISIS
    macro  = checkSPYMacro(spy_data)             # NEW: SPY > 200-SMA? Bull/Bear/Neutral

    if hasOpenPosition():
        manageExits(regime, candle)
        checkPyramidOpportunity(regime, candle)  # NEW: Livermore add-to-winners

    if noOpenPosition() and passesPreFilter(candle):
        if macro == BEAR and signal.direction == LONG:
            skip()                               # NEW: Jones 200-day filter
        signal = generateSignal(regime, candle)
        if signal != NONE:
            checkGapRisk(candle)                  # NEW: overnight gap protection
            size = calculatePositionSize(signal, candle)
            executeTrade(signal, size)

function detectRegime(data):
    ema200_slope = (EMA(200)[-1] - EMA(200)[-21]) / EMA(200)[-21] / 20 * 100
    adx = ADX(14)[-1]
    atr_pctile = percentileRank(ATR(20)[-1], ATR(20).tail(252))

    if atr_pctile > 95 and price < EMA(200) and adx > 30: return CRISIS
    if atr_pctile > 90: return HIGH_VOL
    if ema200_slope > 0.05 and adx > 25 and price > EMA(200): return TREND_UP
    if ema200_slope < -0.05 and adx > 25 and price < EMA(200): return TREND_DOWN
    return RANGE

function checkSPYMacro(spy_data):                # NEW
    spy_sma200 = SMA(spy_data.close, 200)[-1]
    spy_sma50  = SMA(spy_data.close, 50)[-1]
    if spy_data.close[-1] > spy_sma200 and spy_sma50 > spy_sma200: return BULL
    if spy_data.close[-1] < spy_sma200 and spy_sma50 < spy_sma200: return BEAR
    return NEUTRAL

function generateSignal(regime, candle):
    if regime in [TREND_UP, TREND_DOWN, CRISIS]:
        return trendEntry(regime, candle)        # Donchian + EMA + RSI + Volume + ATR + VCP + Darvas
    if regime in [RANGE, HIGH_VOL]:
        return meanReversionEntry(regime, candle) # RSI(3) + EMA proximity + ADX + BB width + corr

function calculatePositionSize(signal, candle):
    base = equity * 0.01 / stop_distance
    conviction = 0.75 if score==5 else 1.25 if score>=6 else 1.0
    vol_mult = [1.25, 1.0, 0.5, 0.25] by ATR percentile quartile
    regime_mult = {TREND: 1.0, RANGE: 0.5, HIGH_VOL: 0.25, CRISIS: 0.25}
    dd_mult = getDrawdownMultiplier(equity, peak)
    macro_mult = 0.5 if SPY_macro == BEAR else 1.0   # NEW
    return min(base * conviction * vol_mult * regime_mult * dd_mult * macro_mult,
               equity * 0.02 / stop_distance)

function manageExits(regime, candle):
    # Priority order:
    1. Stop-loss hit → FULL_EXIT
    2. Gap protection: if open > entry + 5×ATR → FULL_EXIT (blown stop)  # NEW
    3. Time exit: trend=10 bars, MR=5 bars without 1R move
    4. RSI exit (MR only): RSI(3) crosses 70/30
    5. MR target: 1.5R → FULL_EXIT
    6. Trend partial: 3R → close 50%
    7. Breakeven: at 1.5R → move stop to entry
    8. Chandelier trailing: highest_close - 3×ATR (trend, after breakeven)

function checkPyramidOpportunity(regime, candle):  # NEW
    if regime not in [TREND_UP, TREND_DOWN]: return
    if trade.pyramids_added >= 2: return
    if currentR < 1.0 * (trade.pyramids_added + 1): return
    if not donchianBreakout(candle): return
    add_size = original_size * [0.5, 0.3][trade.pyramids_added]
    move_stop_to_breakeven_on_new_add()
    executePyramidEntry(add_size)
```

---

## PHASE 5 — Risk Audit

| Risk | Scenario | Mitigation |
|------|----------|------------|
| **Black swan / flash crash** | Overnight gap blows past stop | Gap protection: if open gaps > 5×ATR past stop, exit at market immediately. Max loss per position capped at 3× initial risk. |
| **Low-volatility whipsaws** | Choppy market, death by 1000 cuts | ADX < 20 → mean-reversion only (0.5× size). Equity curve filter halts after losing streak. BB width < 25th percentile required for MR entry. |
| **High-correlation crisis** | Everything drops together | Max 0.70 pairwise correlation, 0.50 avg portfolio correlation. Max 3 per sector. SPY macro overlay blocks new longs in bear market. |
| **Slippage and fees** | Edge eroded by execution costs | Daily timeframe minimizes trade count (~2-5 trades/week). ATR-based stops ensure stop distance >> typical slippage. Min $10 price filter. |
| **Overfitting** | Strategy only works on trained data | Walk-forward optimization. No more than 6 parameters per sub-strategy. Backtest across 10+ years, multiple market regimes. |
| **Pyramiding risk** | Adding to losers disguised as winners | Only pyramid after confirmed +1R profit AND new Donchian breakout. Max 2 pyramid additions. Each add is smaller (50%, 30%). |

---

## PHASE 6 — Implementation Roadmap

1. **Data sourcing** ✅ — Alpaca API daily bars, 252-day history
2. **Backtesting framework** 🆕 — New `backtest/` module in this PR
3. **Walk-forward optimization** — Use backtester with rolling train/test windows
4. **Paper trading phase** ✅ — Already running on Alpaca paper
5. **Live deployment** ✅ — systemd service, VPS-ready
6. **Scaling plan** — Graduate from paper to live after:
   - 100+ paper trades with profit factor > 1.3
   - Max drawdown < 15% in paper
   - Sharpe > 0.8 on paper equity curve
   - Start live at 25% size, scale up quarterly if targets met
