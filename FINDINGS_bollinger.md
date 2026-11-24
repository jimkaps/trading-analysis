# Bollinger Band strategy research: BTC, NQ, ES, gold

Research log, November 2026. Everything here is a backtest on Dukascopy 1-minute data,
2020-01-01 to 2026-11-12. Nothing has been traded live.

## TL;DR

| Strategy | Result |
|---|---|
| **Bollinger fade (scalp)**, 1/5/15-min bars, 2-5 sigma, with confluence (fib, S/R, dailies, SMA, EMA, VWAP) | **No edge.** Gross edge per trade about zero on all four markets; costs make it negative. Small pockets that look good on one market vanish on the others. |
| **Bollinger breakout (trend-following)**, 5/15-min bars | **Loses after costs** on all four markets. |
| **Bollinger breakout, 60-min bars, stop trailed to the middle band** | **Real edge on BTC**, modest on NQ and gold, about zero on ES. BTC passes every stress test, but the edge is shrinking each year and depends on a few big winners. |
| **Market-structure filters** (HH/HL swing structure, break of structure, squeeze) | **No consistent improvement** on any market. Trading against 60-min structure is worse than no filter, so direction matters a little. |

The one candidate worth paper trading: **BTC 60-min Bollinger(20, 3.0) breakout, stop 1.5 x ATR
trailing to the middle band, 50-bar time stop**. About 109 trades/yr, +0.30% per trade after a 0.05%
fee (about $16k/yr on a $50k position, max drawdown about $16.6k). It earned 0.42%/trade in 2020 but only 0.10% in 2026.

> **Update 24 Nov 2026 — passed its out-of-sample test.** On May 2017 – Dec 2019 BTC data that no
> earlier test used, the same rule made +0.79% per trade, profitable in all 3 years, with all 432
> nearby settings profitable and no random-entry run matching it (longs and shorts). It is a real
> effect. But the edge has shrunk almost every year since 2017 (1.8% → 0.5% → 0.4% → 0.3% → 0.1%
> per trade), which looks like an effect being competed away. See [section 4](#4-out-of-sample-test-may-2017--dec-2019).

---

## Data and method (all studies)

- **Data:** Dukascopy 1-minute BID candles, UTC. `btc_1m.parquet`, `nq_1m_vol.parquet`,
  `es_1m.parquet`, `gold_1m.parquet` (not in git; fetch with `fetch_data.py`).
  - BTC has no Saturday data and some flat zero-volume filler in 2020/2022-23.
  - NQ/ES/gold include flat zero-volume bars while the market is closed; these are dropped
    (`--drop-filler`) so they don't distort bands and ATR.
  - Prices are BID only, so the spread is not in the data and has to come out of the cost assumption.
- **Signals** on 1/5/15/60-min bars resampled from 1-min data. **Entry at the next 1-minute open.**
- **Exits simulated minute by minute.** If the stop and target are both hit in the same minute, it is
  counted as the stop.
- **One position at a time** per setting and filter. Signals during an open trade are skipped.
- **Costs per round trip:**
  - BTC: 0.05% of position (also tested 0.02 / 0.10 / 0.20 / 0.30%)
  - MNQ: 1 pt slippage + $1.24 (about 0.011%/trade)
  - MES: 0.5 pt + $1.24 (about 0.016%)
  - MGC: 0.2 pt + $1.24 (about 0.015%)
- **Periods:** choose settings on 2020-23, check on 2024-25, final check on 2026.
- **$ figures** assume a fixed $50,000 position per trade.
- **Robustness tests used throughout:**
  - Nearby settings, so we judge the neighbourhood rather than the best cell.
  - Hourly or 15-min bars shifted in start time (:00 / :05 / :10, or :00 / :15 / :30 / :45).
  - Random filters or random entries with the same trade count, a placebo test.
  - Entry 1-60 minutes late.
  - Long vs short split, to separate a real effect from BTC's and NQ's price rise.
  - The same rules on the other markets.

---

## 1. Bollinger fade (mean-reversion scalp) with confluence

**Script:** `bb_scalp.py`

**Rules:**
- **Entry:** BB(20) at 2 / 2.5 / 3 sigma. Either "reject" (bar touches the band and closes back
  inside) or "close" (bar closes outside the band); fade the move.
- **Exits:** TP at the middle band or at 1R / 1.5R. SL at 1 / 1.5 / 2 x ATR14. Time stop after 20 bars.
- **Confluence:** the signal bar must test a level (within 0.25 x ATR):
  - fib 38.2 / 50 / 61.8 of the prior UTC day
  - prior-day high, low and close, and today's open
  - prior-week high and low
  - the last 12 confirmed 15-min fractal swing points
  - SMA200, EMA200, daily VWAP
  - "any level", "2+ levels", and the 60-min EMA200 trend (with or against)

**Grid:** 162 settings x 15 filters per market.

| Market | Gross edge/trade, no filter | After costs, no filter | Settings profitable in every period |
|---|---|---|---|
| BTC (0.05% fee) | -0.006% to +0.004% | about -0.05% | 6 of 2,066 (at 0.02% fee); 0 at 0.05% |
| NQ (MNQ) | about 0.000% | about -0.010% | 17 of 2,041 |
| ES (MES) | about 0.000% | about -0.015% | 0 of 2,038 |
| Gold (MGC) | about 0.000% | about -0.015% | 0 of 2,026 |

- Win rate is about 45-47% everywhere.
- Most confluence filters made results *worse*. "2+ levels" never helped.
- On 1-5 min bars the typical bar range (0.05-0.09% on BTC) is about the size of the cost.

### Leads that were stress-tested and rejected

**BTC: 15m close outside 2.5-3 sigma + VWAP test** (`bb_vwap_check.py`)
- 2,916 nearby settings. The median trade was +0.063% in 2020-23, +0.020% in 2024-25 and -0.028% in 2026.
- It depends on bar alignment: 51% of settings made money in every period with bars starting at :00, only 3% at :10.
- Entering 1 minute late halves it.
- It doesn't carry over to NQ, ES or gold. **Rejected.**

**NQ: 15m 3-sigma reject + EMA200 test** (`bb_nq_check.py`)
- 3,888 nearby settings. 71% are positive after costs, and it beat random filters (p = 0.001 at 3 sigma).
- It survives late entry and double slippage.
- **But** the median trade in 2024-25 was negative, and it fails on ES (1% of settings positive in every
  period) and on gold.
- Verdict: the most real-looking fade result, but weak, fading and NQ-only. Paper trade at most.
  Pine script: `nq_bb_ema_strategy.pine`.
- "Any level + 60m trend" on NQ was positive in all 7 years, but it was a lucky corner of the grid and
  fell apart under testing.

### Wider bands: 3 / 3.5 / 4 / 4.5 / 5 sigma (all markets)

- With a 20-bar population std that includes the current close, a close can be at most
  19/sqrt(20) = **4.25 sigma** from the mean. So "close outside" signals cannot exist at 4.5 or 5 sigma;
  only "touch and reject" works there.
- Wider bands just mean fewer trades and more noise. Median net per trade was negative at every
  width on every market.
- 23 of 5,400 combinations were profitable in every period, almost all in the same NQ 15m corner,
  with long-side bias and small samples. **No edge.**

---

## 2. Bollinger breakout (trend-following) with market structure

**Scripts:** `bb_breakout.py` (sweep) and `bb_breakout_check.py` (60m checks and drift control)

**Rules:**
- **Entry:** the first close outside the 2 / 2.5 / 3 sigma band on 5 / 15 / 60-min bars. Trade
  *with* the break at the next 1-min open.
- **Exits:** 2R or 3R target; "mid" (stop trails to the middle band); or a chandelier trail.
  Stop 1 / 1.5 / 2 / 3 x ATR. Time stop after 50 bars.
- **Market-structure filters,** using fractal swings with 2 bars each side, only once confirmed:
  - Swing structure: the last two swing highs AND lows rising (HH + HL) for longs, falling for shorts, on 15m or 60m.
  - Break of structure (BOS): the breakout close is also beyond the last 15m swing high or low.
  - BOS + 60m structure.
  - Against 60m structure, as a sanity check.
  - Squeeze: band width in the lowest 20% of the last 500 bars.
  - Squeeze + BOS, squeeze + 60m structure.
  - 60m EMA200 trend.

**Results:**

1. **5m and 15m breakouts lose after costs on every market.** For example, the median 15-min trade
   with no filter lost about 0.01-0.02%.
2. **60-min breakouts work, best with the "mid" exit.** For 3 sigma, SL 1.5 ATR, no filter:

| Market | Trades/yr | Net/trade | $/yr per $50k | Max DD | 2020-23 | 2024-25 | 2026 |
|---|---|---|---|---|---|---|---|
| BTC | 109 | 0.30% | ~$16.3k | ~$16.6k | 0.37% | 0.21% | 0.10% |
| NQ | 86 | 0.09% | ~$4.0k | ~$8.0k | 0.11% | 0.09% | 0.02% |
| Gold | 71 | 0.09% | ~$3.3k | ~$3.6k | 0.08% | 0.04% | 0.31% |
| ES | 81 | 0.03% | ~$1.4k | ~$5.8k | 0.03% | 0.07% | -0.06% |

3. **Drift control.** BTC rose about 10x and NQ about 2.5x over 2020-26, so each breakout side was
   compared with *random* hourly entries using the same exits and costs:
   - BTC: breakout longs beat random longs by about 0.21% per trade, and shorts beat random shorts by
     about 0.10%. 92% of settings beat random on both sides.
   - NQ: 69% of settings beat random on both sides.
   - ES: 40%. Gold: 42%, about as good as random.
4. **Market structure doesn't help consistently.**
   - 60m structure helps NQ/ES slightly but hurts BTC: 21% of settings profitable in every period,
     vs 73% with no filter.
   - 15m structure and BOS add nothing.
   - "Against 60m structure" is worse than no filter almost everywhere.
   - Only 2 of 480 hourly settings were profitable in every period on all four markets, both
     squeeze + 60m structure, at about 28 trades/yr. Too thin to trust.

---

## 3. BTC 60-min breakout: full stress test

**Script:** `btc_breakout_stress.py`

**Core rules:** BB(20, 3.0) on 60m bars (UTC). The first close outside the band triggers a trade with
the break at the next 1-min open. The stop starts at 1.5 x ATR14(60m) and trails to the middle band.
Time exit after 50 bars. Fee 0.05%.

**Passed:**
- **Nearby settings:** 864 variants (length 15/20/30, 2.25-3.5 sigma, stop 1-3 ATR, time stop
  25/50/100 bars, bar start :00/:15/:30/:45). **100% positive overall** and 75% positive in every
  period. The median was 0.29%/trade, very close to the core setting.
- **Random entries:** 2,000 draws with the same trade count, long/short mix and exits. Random median
  -0.02%/trade; **none matched +0.30%.** Shorts also beat random (p = 0.005).
- **Late entry:** 1 / 5 / 15 / 60 minutes late gives 0.25 / 0.27 / 0.32 / 0.26% per trade.
- **Weekend gap:** Dukascopy has no Saturday data. Going flat before every data gap gives
  0.24%/trade, positive every year.
- **Walk-forward:** each year from 2022, use the best of 48 settings over the previous two years.
  Profitable in 2022, 2023, 2024 and 2026; 2025 lost about $4.4k.

**Warnings:**

| | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| Net % per trade | 0.42 | 0.36 | 0.30 | 0.40 | 0.28 | 0.12 | 0.10 |
| $ per $50k position | 27.6k | 14.8k | 18.8k | 27.0k | 14.8k | 5.2k | 3.9k |

- **The edge is shrinking**, from 0.4%/trade in 2020-23 to about 0.1% in 2025-26.
- **Profit is concentrated.** Win rate 36%, average win 2.5% vs average loss 0.9%. The best 5% of
  trades earn more than 100% of the profit, and without them the rest lose 0.12%/trade.
- **Fees.**
  - At 0.10% round trip (about perp taker): 0.25%/trade, but 2026 drops to +0.05%.
  - At 0.20%: 2026 goes negative, and only 30% of nearby settings stay positive in every period.
  - The data is BID only, so add the spread. Perp funding would also apply to trades held for about 12 hours.
- **Drawdowns.** Max drawdown about $16.6k, a third of the $50k position before leverage. The longest
  stretch without a new high was 378 days. The worst 12 months lost $3.9k. 19 of 28 quarters
  were positive.
- **Longs and shorts take turns.** Longs carried 2020, 2023 and 2024; shorts carried 2025.

**Verdict:** a real effect, unlike everything in section 1: it beats random entries, doesn't depend on
exact settings and survives realistic execution. But it's thin and shrinking. Paper trade, or trade
very small with low fees. If 2025-26 is the new normal, ordinary taker fees would take most of it.

---

## 4. Out-of-sample test: May 2017 – Dec 2019

Added 24 Nov 2026 (`btc_oos_test.py`, data `btc_1m_2017_2026.parquet` = Dukascopy BTCUSD from
7 May 2017, the earliest it has, plus the original 2020–2026 file). Same rule and code, nothing changed.
2017–19 has more flat filler minutes (19–25% vs 12% in 2020 and ~1% since 2024); on 60-min signals
this matters little, but intrabar stop fills are slightly less precise in those years.

**Core rule by year** (0.05% fee, $ on a $50k position):

| Year | Trades | Net % / trade | $ | Win % | Longs | Shorts |
|---|---|---|---|---|---|---|
| 2017 (May–Dec) | 77 | 1.81% | $69,536 | 39% | 2.27% | 1.15% |
| 2018 | 154 | 0.55% | $42,206 | 30% | 0.24% | 0.82% |
| 2019 | 159 | 0.53% | $41,733 | 32% | 0.64% | 0.42% |
| 2020 | 133 | 0.42% | $27,596 | 32% | 0.75% | 0.05% |
| 2021 | 83 | 0.36% | $14,807 | 37% | 0.40% | 0.32% |
| 2022 | 126 | 0.30% | $18,820 | 39% | 0.33% | 0.28% |
| 2023 | 136 | 0.40% | $26,972 | 32% | 0.69% | −0.01% |
| 2024 | 105 | 0.28% | $14,801 | 43% | 0.81% | −0.19% |
| 2025 | 89 | 0.12% | $5,215 | 37% | −0.14% | 0.34% |
| 2026 | 79 | 0.10% | $3,859 | 33% | 0.38% | −0.12% |

2017–19: +0.79% per trade, about $51k a year on $50k, worst drawdown $6.2k, 3 of 3 years profitable.
2018 was a bear market and shorts carried it, so this isn't just riding BTC's rise.

**Checks on 2017–19:**
- **Nearby settings:** all 432 variations (band length 15/20/30, width 2.5–3.25σ, stop 1–2 ATR, time
  stop 25/50/100 bars, bar start :00/:15/:30/:45) made money; 98% made money in every year. Median
  0.52% per trade, against 0.29% for the same settings in 2020–26.
- **Random entries:** same trade count, long/short mix and exits at random hourly closes, 2,000 draws:
  random median +0.05% per trade, 95th percentile +0.21%; the breakout's +0.79% was never matched
  (p < 0.0005 for all trades, longs and shorts).
- **Costs and execution:** +0.64% per trade at a 0.20% fee; +0.63–0.65% entering 5–15 minutes late;
  +0.75% going flat before every data gap.

**What this means:**
- **This is a real, long-standing effect:** it held on years it was never fitted to, across settings,
  both directions, and against random entries. That is a much stronger result than NQ preset E, which
  failed the same kind of test.
- **But it is decaying.** Per-trade edge fell from 1.8% (2017) to about 0.5% (2018–19), 0.3–0.4%
  (2020–23), 0.28% (2024) and 0.10–0.12% (2025–26). Falling volatility doesn't explain it: BTC's
  typical minute range in 2024–26 (0.055–0.074%) was higher than in 2018–19 (0.029–0.038%), yet the
  edge was a quarter as large. The likeliest explanation is more traders running trend-following
  breakouts on BTC.
- **Practical rule:** only trade it with low fees (≤ 0.05% round trip including spread), small size,
  and a kill switch, for example stop if a rolling 12 months averages below +0.10% per trade
  after fees. At 2025–26 levels it is barely worth the effort.

---

## Reproducing

All scripts run with the project's virtual environment from this folder, and each finishes in under a minute.

```bash
# 1. Fade / scalp sweep (add --stds=3,3.5,4,4.5,5 for the wide-band test)
.venv/Scripts/python.exe bb_scalp.py btc_1m.parquet bb_scalp_results.parquet
.venv/Scripts/python.exe bb_scalp.py nq_1m_vol.parquet bb_scalp_nq.parquet --drop-filler --mnq
.venv/Scripts/python.exe bb_scalp.py es_1m.parquet bb_scalp_es.parquet --drop-filler --mes
.venv/Scripts/python.exe bb_scalp.py gold_1m.parquet bb_scalp_gold.parquet --drop-filler --mgc

# Fade leads stress tests
.venv/Scripts/python.exe bb_vwap_check.py   # BTC 15m VWAP lead (+ NQ/ES/gold)
.venv/Scripts/python.exe bb_nq_check.py     # NQ 15m 3-sigma reject + EMA200 (+ ES)

# 2. Breakout sweep with market structure, then 60m checks / drift control
.venv/Scripts/python.exe bb_breakout.py
.venv/Scripts/python.exe bb_breakout_check.py

# 3. BTC 60m breakout stress test
.venv/Scripts/python.exe btc_breakout_stress.py

# 4. Out-of-sample 2017-19 (download first, then join with btc_1m.parquet into btc_1m_2017_2026.parquet)
DUKA_INSTR=BTCUSD DUKA_SCALE=10 .venv/Scripts/python.exe fetch_data.py 2017-01-01 2019-12-31 btc_1m_2017_2019.parquet 6
.venv/Scripts/python.exe btc_oos_test.py btc_1m_2017_2026.parquet
```

## Files

| File | What it is |
|---|---|
| `FINDINGS_bollinger.md` | This document |
| `bb_scalp.py` | Bollinger fade sweep with 15 confluence filters; options `--drop-filler`, `--mnq/--mes/--mgc`, `--stds=` |
| `bb_vwap_check.py` | Stress test of the BTC 15m VWAP fade lead |
| `bb_nq_check.py` | Stress test of the NQ 15m 3-sigma reject + EMA200 fade |
| `nq_bb_ema_strategy.pine` | TradingView strategy for the NQ EMA200 fade (paper trading) |
| `bb_breakout.py` | Bollinger breakout sweep with market-structure filters, four markets |
| `bb_breakout_check.py` | 60m breakout checks: cross-market consistency and random-entry drift control |
| `btc_breakout_stress.py` | Full stress test of the BTC 60m breakout |
| `btc_oos_test.py` | Out-of-sample test of the BTC 60m breakout on May 2017 – Dec 2019 |
| `btc_bb_breakout.pine` | TradingView strategy for the BTC 60m breakout (1-hour chart), same rules as the tests |

Result tables (`*.parquet`) are regenerated by the scripts and are not committed.
