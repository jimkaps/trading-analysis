# Strategies in use (as of 24 Nov 2026)

Four strategies are live or being set up. Everything else has been retired (list at the end).
Backtest details and the tests behind each decision are in [FINDINGS_2026-11-24.md](FINDINGS_2026-11-24.md).

| Strategy | Market / account | Code | Alerts |
|---|---|---|---|
| **1. NQ ORB, preset E** | MNQ futures, own account / reference (on Lucid use 4) | `nq_orb_strategy.pine` (TradingView "NQ Opening Range Breakout (A/B/C/D)", version 5) | TradingView alert "NQ ORB E": app, email and pop-up |
| **2. IBS, phone-app rule** | US Tech 100 CFD, Trading 212 (by hand) | Android app "IBS Assistant": repo `jimkaps/android_kernel_samsung_crespo`, branch `claude/sharp-franklin-o9bmsa` | The app's own phone notifications |
| **3. BTC 4h SFP + VOL** | BTCUSDT perpetual, Phemex (automated bot, runs elsewhere) | TradingView "BTC 4h SFP+VOL" version 1; the bot's code is not in this repo | TradingView alert on PHEMEX:BTCUSDT.P 4h: app only (cross-check of the bot) |
| **4. NQ ORB E, Lucid prop mode** | MNQ futures, Lucid Flex 50K | `nq_orb_prop.pine` (TradingView "NQ ORB E - Lucid prop") | TradingView alert "ORB E prop": app, email and pop-up |

## 1. NQ ORB, preset E

- **Rules:** range 07:30–08:30 London; buy-stop at the range high, sell-stop at the low, first fill only;
  stop 1 × 14-day average daily range; no take-profit; flat at 15:55 New York.
- **TradingView:** on the "Unnamed" layout, MNQ1! 5-minute. Version 5 adds alerts (range set, entry filled,
  stop-loss / take-profit / time exit) and plots the open trade's entry, stop and target. Slippage 2 ticks per side.
- **Alert:** "NQ ORB E", condition "Order fills and alert() function calls", message
  `{{strategy.order.alert_message}}`, no expiry. Recreate it if the script is saved again.
- **Backtest, 1 MNQ:** +$55.6k over Jun 2013 – Nov 2026, max drawdown $7.2k. All of it since 2020;
  2013–19 lost $3k and no nearby setting worked then.
- **Lucid:** Flex fits best. 2020–26: Flex 50K 2/1 (eval/funded MNQ) ≈ $3.5k/yr, worst drop $794;
  Flex 50K 3/3 ≈ $6.0k/yr; Flex 150K 5/2 ≈ $6.5k/yr. Every plan loses money on 2014–19.
- **On Lucid, run strategy 4 instead** (same trades, prop-specific management). Plain E stays the reference and
  the version for an own account, where a profit cap would cut the big days that make its money.

## 2. IBS, phone-app rule

- **Rules:** decide 10 minutes before the US close; buy if (IBS today < 0.3 and yesterday < 0.3) or IBS today
  < 0.1 or RSI(2) < 10; never buy on a Friday; exit at the next close unless the signal fires again; no stop.
- **Size:** £500 per trade for a 30-day trial, then £2,000 if real costs are ≤ 0.05% per trade (≈ +£180/yr).
- **Backtest, 1 MNQ equivalent:** +$33.4k over 2013–26 (+$2,487/yr), max drawdown $3.0k, no losing year.
- **Not for Lucid:** it holds overnight, and prop accounts must be flat each day.
- **Open items:** the app's signing key is committed publicly (move it to a GitHub secret); confirm whether
  Trading 212's £ order box is position value or margin before the first trade.

## 3. BTC 4h SFP + VOL

- **Rules:** two halves of the risk. SFP: a wick through the 20-bar low (high) that closes back inside, with the
  EMA 50/200 trend. VOL: volume > 2 × its 50-bar average and body > 0.8 × ATR, with the trend. ATR trailing stops
  (2 × and 2.5 ×), 60-bar time exit, 1% risk, max 3× leverage, smaller in volatile markets.
- **Backtest ($10k, Dec 2022 – Nov 2026, TradingView):** 298 trades, +$7,970, profit factor 1.87,
  max drawdown $822, every year positive. Live since 7 Nov 2026: one trade, −$13.

## 4. NQ ORB E, Lucid prop mode

Preset E with the account management optimized for Lucid Flex 50K (`prop_optimize.py`, findings in
[FINDINGS_orb_prop.md](FINDINGS_orb_prop.md), last section). **Same entries, stops and exits as E.**

**How it works**

| | Evaluation | Funded |
|---|---|---|
| Contracts | 2 MNQ | 2 MNQ |
| Daily profit cap | **$1,200**: a take-profit that closes the day's trade once it's up $1,200 after costs | None |
| Why | Lucid needs best day ≤ 40% of total profit. With the cap no day can exceed $1,200 = 40% of the $3,000 target, so one big trend day can't push the pass out to $6,000+. Profit beyond the target is worth nothing in an evaluation anyway. | No consistency rule once funded, so E keeps its big days, which is where its profit comes from. |

**Backtest, Lucid Flex 50K, net per year after all fees** (start dates every 2 months):

| | Plain E (2 eval / 1 funded) | **Prop mode** |
|---|---|---|
| 2020–26, typical start | $3,949 | **$7,270** |
| 2020–26, worst start | $3,455 | **$6,075** |
| 2014–19 (E had no edge) | −$249 | **+$2,728** |
| Evaluations bought 2020–26 | 68 | 96 |

Part of the gain is Lucid's pricing rather than E: with random trade direction the same plan still nets about
+$2.2k/yr in the model ($88 resets, 90% payouts). That holds only while Lucid keeps these rules.

**Process**

*Set up (once)*
1. In TradingView, add `nq_orb_prop.pine` ("NQ ORB E - Lucid prop") to an MNQ1! 5-minute chart. Inputs:
   Account phase **Evaluation**, contracts 2 / 2, cap **1200**.
2. Create the alert: condition "Order fills and alert() function calls", message
   `{{strategy.order.alert_message}}`, no expiry. Turn off the plain "NQ ORB E" alert so you don't get two sets.
3. Buy a Lucid Flex 50K evaluation with the coupon (≈ $88). Leave the optional daily loss limit off and the
   consistency at 40%.

*Every trading day*
4. At 08:30 London the "range set" alert gives the levels. Place a buy-stop at the range high and a sell-stop at
   the range low, 2 MNQ each, one-cancels-other, each with its stop-loss (and, in the evaluation, the take-profit
   at the cap level) from the alert.
5. When one side fills, cancel the other. Don't move the stop or target.
6. At 15:55 New York close anything still open (the alert tells you). Lucid flattens at 16:45 New York anyway.

*Evaluation*
7. Pass = $3,000 profit with best day ≤ 40% (the cap guarantees that part); usually at least 3 trading days.
8. If the balance hits the trailing floor, the evaluation is failed: reset it (≈ $88) and carry on the next day.

*Once funded*
9. Change the input to **Funded** (cap off) and **recreate the alert**: TradingView alerts keep the inputs they
   were created with.
10. Request a payout once there are 5 days of ≥ $150 profit since the last one and the cycle is positive:
    up to 50% of profit, max $2,000, min $500; you get 90%.
11. After 5 payouts Lucid moves the account to live; re-check the live rules before trading it.
12. If the funded account busts: buy a new evaluation, switch the input back to **Evaluation**, recreate the alert.

*When to stop*
13. Stop buying evaluations after 5–6 in a row without a payout, and review if 12 months of results are negative
    (a losing year happens ~8% of the time if the edge is real, ~57% if it isn't).

## All three together

Backtest, Jun 2013 – Nov 2026 (ORB and IBS at 1 MNQ, SFP+VOL on $10k from Dec 2022): **+$97.0k, max drawdown
$7.5k.** Since Dec 2022 with all three running: +$67.9k, max drawdown $5.7k. ORB and IBS trade different
accounts, so their orders never clash; ORB vs IBS daily correlation is low (+0.09 with the TradingView IBS rule).

## Retired (24 Nov 2026)

| Strategy | Why | What was done |
|---|---|---|
| IBS long (TradingView, NQ) | Weaker than the app's IBS rule ($1,768/yr vs $2,487/yr, twice the drawdown) | Kept as a script with alerts (`ibs_long_strategy.pine`); no alert set |
| NQ ORB combo (prop) | ≈ $4.70/trade at 1 MNQ, about its own costs; lost money in 2026 | Removed from the layout (`tv_fixed/nq_orb_combo_prop_fixed.pine` kept) |
| ORB15 signals (TP/SL) | Untested third ORB | Its TradingView alert is turned off |
| BB Breakout (No Trail / TP-SL-Trail) on Bybit BTC | Profit factor 1.06–1.07 after costs; drawdowns as big as the total gain | Both alerts deleted; scripts deleted from TradingView (fixed copies in `tv_fixed/`) |
| BTC 4H Donchian v7, H4 | Draft scripts on the NQ layout; can't size on MNQ | Removed from the layout (fixed copies in `tv_fixed/`) |
