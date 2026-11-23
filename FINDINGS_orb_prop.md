# NQ Opening Range Breakout and prop-firm research: findings

Consolidated from the Claude Code sessions "NQ trading strategy variants" (plus forks 2 and 3), 13 Nov 2026.
The Bollinger Band research (sessions "Local BTC data" and its fork, 19 Nov 2026) is in
[FINDINGS_bollinger.md](FINDINGS_bollinger.md).

Data: Dukascopy 1-minute bars, Jan 2020 to Nov 2026 (Nasdaq-100 index as a stand-in for NQ futures; also
S&P 500, BTCUSD, XAUUSD). Costs: 1 tick slippage per side plus $0.62 commission per side per micro contract.
All P&L is after costs unless stated.

## Bottom line

- **Best strategy: preset E on MNQ.** London 07:30–08:30 range breakout, stop = 1 × 14-day average
  daily range, no take-profit, flat at 15:55 New York.
- **1 MNQ, 2020 – Nov 2026:** +$58,526 (15:55 NY exit), worst drawdown −$7,164, profitable 7 of 7 years.
  About a third of the profit came in 2026; 2020–25 averaged about $6k a year.
- **Your original setup A** made +$15,151 on the same data, with a −$7,690 worst drawdown.
- **More than 300 add-ons failed.** The edge is simple: take the morning breakout, give it room in
  proportion to volatility, hold to the US close.
- **ES:** profitable but redundant (0.67 daily correlation with NQ). **BTC:** loses at both fee levels.
  **Gold:** weak alone, but uncorrelated with NQ (0.05), so a small add-on improves return ÷ drawdown.
- **Prop route:** E on a 50K account at 2 MNQ ≈ $4–5k/yr net (6-payout cap). 150K, pass at 5 MNQ then
  2 MNQ funded ≈ $4.1k/yr with half as many evaluations and the best worst-case start.
- **No setup reliably passes one evaluation and keeps one funded account alive for a year.** Budget for
  several evaluations, or trade your own account with $8–10k of buffer.

## Presets (TradingView script `nq_orb_strategy.pine`)

| Preset | Range (London) | Take-profit / stop | Exit |
|---|---|---|---|
| A (original) | 07:30–08:20 | 205 / 211 points | 16:00 London |
| B | 07:30–08:20 | +1.5% / −0.5% | 21:00 London |
| C | 15:00–15:30 | ±1% | 18:30 London |
| D | 07:30–08:30 | none / −1% | 15:55 New York |
| **E (default)** | 07:30–08:30 | none / 1 × 14-day avg daily range (~460 pts, ~$920 per MNQ) | 15:55 New York |
| NY (forward test) | 10:00–10:30 New York | 0.5 × / 0.2 × avg daily range | 15:55 New York |

Entry for all: buy stop at range high, sell stop at range low, first fill only, one trade a day.
The script is saved to TradingView as "NQ Opening Range Breakout (A/B/C/D)" with E as default.
The 15:55 New York exit keeps you flat before prop firms' 16:10–16:59 NY cut-offs, including the weeks
when UK and US clocks change on different dates.

## Preset E results

| 1 MNQ, 2020 – Nov 2026 | A (original) | D | **E** |
|---|---|---|---|
| Total P&L | +$14,835 | +$36,790 | **+$56,501** (+$58,526 with NY exit) |
| Worst drawdown | −$7,690 | −$7,918 | **−$7,164** |
| Win rate | 50% | – | 51% |
| Profitable years | 4 of 7 | 6 of 7 | **7 of 7** |

E by year: 2020 +$4,516 · 2021 +$204 · 2022 +$13,115 · 2023 +$5,201 · 2024 +$5,120 · 2025 +$8,278 ·
2026 +$20,067. Weekly equity curve: `e_curve.json`.

**Why it is trusted:**
- Holds across nearby settings: start 07:15–07:45, range 45–90 min, exit 19:30 or 20:55, stop 0.8×–1.5×
  average range. Better than D on 100% / 94% / 72% of 18 nearby settings in 2020–23 / 2024–25 / 2026.
- It is the adaptive part that matters: fixed 1.5%, 2% and 2.5% stops did clearly worse in 2024–25.
- On ES (not used in design) the ATR stop beat the 1% stop on 94% / 83% / 100% of settings.

**Watch-outs:**
- 2026 has been looked at many times, so it is no longer a clean out-of-sample year.
- Index data, not futures; TradingView futures match closely only for Aug–Nov 2026.
- Aug–Nov 2026 E was weaker than D (drawdown −$4.3k vs −$1.9k). Worst historical drawdown ran
  late Apr – mid Jun 2025; drawdowns of $2–4k with months-long recoveries are normal.
- TradingView's daily range includes the overnight session, so its stops sit slightly wider.

## What failed on top of D/E

| Idea | Result |
|---|---|
| 23 confluence filters | ❌ |
| 48 EMA/SMA entry filters (incl. daily EMA200 side) | ❌ worse in 2026 on all 72 settings |
| 9 moving-average trailing exits | ❌ −$2k to −$12k per period |
| 6 VWAP tests (07:00, midnight, 23:00 anchors; filter and exit) | ❌ |
| 180 Fibonacci retracement entries | ❌ 0 beat the breakout entry |
| 28 supply/demand zone rules (origin, room-to-run, targets) | ❌ origin rule worst of all |
| Stop-and-reverse | ❌ about −$5k in 2020–23 |
| Entry buffer / 5-min close confirmation | ❌ |
| Partial profits at +1 / 1.5 / 2% | ❌ |
| Later exits (21:55, 23:00, midnight) | ❌ |
| Volatility position sizing | ➖ neutral |
| Break-even stop after +1% | ✅ small gain on D, not added to E |
| **ATR (volatility) stop** | ✅ became preset E |

Scripts: `orb_sweep.py`, `confluence.py`, `ma_test.py`, `fib_test.py`, `sd_test.py`, `extra_test.py`,
`stop_test.py`, `analyze.py`, `factors.py`, `regions.py`, `pick_morning.py`, `compare.py`.

## Other markets (`market_test.py`, `btc_test.py`)

| | Result |
|---|---|
| ES (1 MES) | E +$23,423, DD −$6,061, 6 of 7 years; fragile (39% of nearby settings positive in 2024–25); mostly 2026. 1 MNQ + 1 MES ratio 7.2 vs 2 MNQ 7.9 → skip |
| BTC ($50k position) | Loses: Phemex fees (0.12%) D −$95k, E −$103k; low fees (0.05%) D −$33k, E −$41k. Average trade negative before sizing |
| Gold ($50k ≈ 1.3 MGC) | D +$24,292 (6/7 yrs), E +$31,517 (4/7 yrs); avg trade ~⅓ of NQ |
| NQ E + gold E | +$114,654, DD −$11,506, total ÷ DD 10.0 vs 7.4 for NQ alone or doubled |

## Prop-firm simulations

Model: buy a $150 (50K) or $350 (150K) evaluation, trade until pass or bust, take payouts when funded
(5 days of $150+ profit, max $2,000 per payout, $2,000 buffer, 90% split), buy the next after a bust.
Most realistic version caps payouts at 6 per funded account.

**E, Jan 2020 – Nov 2026:**

| Plan (6-payout cap) | Money in | Net by Nov 2026 | Net/yr 2020–25 (median start) | Worst start month | Worst drop |
|---|---|---|---|---|---|
| **150K, pass at 5 → funded 2 MNQ** | $20,300 (58 evals) | +$41,384 | $4,069 | **$3,369** | −$3,500 |
| 150K, 5 MNQ throughout | $39,900 (114 evals) | +$66,990 | $7,662 | $1,250 | −$9,228 |
| 50K, 2 MNQ throughout | $13,500 (90 evals) | +$34,286 | $4,474 | $2,445 | −$2,100 |
| 50K, pass at 2 → funded 1 | $8,850 (59 evals) | +$19,564 | $1,639 | $158 | −$1,800 |
| Own $2k account, 1 MNQ | $2,000* | +$58,555 | $6,300 | $4,915 | −$7,164 |
| A, 150K 5→2 | $18,550 | +$5,586 | −$742 | −$3,328 | −$8,094 |
| A, 50K 2 MNQ | $11,100 | +$3,876 | $442 | −$558 | −$2,761 |
| A, own $2k | $6,000 | +$15,580 | $873 | −$739 | −$7,690 |

\*Jan 2020 start never busted; 26 of 48 start months busted at least once and needed another $2,000.
Without the payout cap, E 50K 2 MNQ nets +$59,034, but most of the difference is one 2026 account paying 19 times.

**Findings:**
- **$2,000 is too small for E in your own account** (one stop ≈ $920; losing streaks $3–7k). You need
  about $8–10k for 1 MNQ.
- **Risk controls on E don't help prop survival** (fixed-dollar risk, size-down near limit, break-even,
  tighter or capped stops): each trims the big trend days that make the money. A $600 stop cap looked
  good but $500 and $550 were much worse, so it's luck.
- **Account size helps:** 150K (pass 5, funded 2) doubles funded account life (51 vs 24 trading days),
  cuts evaluations from 12.6 to 8.1 a year, similar income.
- **Single-account survival:** of ~12,000 setups at 1–5 MNQ on 50K and 150K, no setup reliably passes and
  survives a year funded. E: 0% at every size. Best found (NY 09:45–09:50 range, 0.15× ATR stop, 1 MNQ):
  28%, ranging 0–85% by start year, 0% for 2025 starts.

**Suggested plan with $2,000:** use it for 50K evaluations at 2 MNQ (or 150K 5→2 for steadiness), bank
payouts into your own account, and start trading 1 MNQ there once it reaches about $10,000.
Paper-trade E for a few weeks first and compare fills with the backtest.

Scripts: `prop_sim.py`, `prop_paths.py`, `prop_detail.py`, `prop_lifecycle.py`, `prop_lifecycle_150k.py`,
`prop_50k_1mnq.py`, `prop_funded_size.py`, `prop_search.py`, `prop_rank.py`, `prop_strat.py`,
`prop_e_ny_50k.py`, `combo_prop.py`, `combo_funded.py`, `combo_robust.py`, `streams.py`,
`own_account.py`, `risk_sim.py`, `risk_cap_check.py`, `risk_structure.py`, `single_acct.py`,
`single_rank.py`, `single_check.py`, `survive_search.py`, `survive_pct.py`, `compare_all.py`,
`exit_ny_check.py`.
