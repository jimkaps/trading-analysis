# Strategies in use (as of 24 Nov 2026)

Three strategies are live or being set up. Everything else has been retired (list at the end).
Backtest details and the tests behind each decision are in [FINDINGS_2026-11-24.md](FINDINGS_2026-11-24.md).

| Strategy | Market / account | Code | Alerts |
|---|---|---|---|
| **1. NQ ORB, preset E** | MNQ futures, Lucid prop account | `nq_orb_strategy.pine` (TradingView "NQ Opening Range Breakout (A/B/C/D)", version 5) | TradingView alert "NQ ORB E": app, email and pop-up |
| **2. IBS, phone-app rule** | US Tech 100 CFD, Trading 212 (by hand) | Android app "IBS Assistant": repo `jimkaps/android_kernel_samsung_crespo`, branch `claude/sharp-franklin-o9bmsa` | The app's own phone notifications |
| **3. BTC 4h SFP + VOL** | BTCUSDT perpetual, Phemex (automated bot, runs elsewhere) | TradingView "BTC 4h SFP+VOL" version 1; the bot's code is not in this repo | TradingView alert on PHEMEX:BTCUSDT.P 4h: app only (cross-check of the bot) |

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
- **Suggested start (updated 24 Nov, `prop_optimize.py`):** Lucid Flex 50K, 2 MNQ in the evaluation with a
  **$1,200 daily profit cap** (script input "Evaluation daily profit cap"), 2 MNQ once funded with the cap off.
  2020–26 ≈ $7.3k/yr (worst start $6.1k) vs $3.9k for the old 2/1 plan; +$2.7k/yr even on 2014–19.
  Stop buying evaluations after 5–6 without a payout.

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
