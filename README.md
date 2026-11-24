# nq_orb: trading strategy research

Backtests on Dukascopy 1-minute data (NQ, ES, BTC, gold; Jan 2020 – Nov 2026).

## Strategies in use (24 Nov 2026)

1. **NQ ORB, preset E** on MNQ (Lucid prop account): TradingView alert "NQ ORB E".
2. **IBS, phone-app rule** on the US Tech 100 CFD (Trading 212): the IBS Assistant Android app.
3. **BTC 4h SFP + VOL** on Phemex (automated bot): TradingView alert as a cross-check.

Rules, sizes, alerts and what was retired: [STRATEGIES.md](STRATEGIES.md).

## Start here

| Document | What it covers |
|---|---|
| [STRATEGIES.md](STRATEGIES.md) | The three strategies in use, how each one alerts, and what was retired |
| [FINDINGS_2026-11-24.md](FINDINGS_2026-11-24.md) | TradingView script check and fixes, ORB vs IBS, app IBS vs TradingView IBS, ORB combo vs E, combined P&L, Lucid |
| [FINDINGS_orb_prop.md](FINDINGS_orb_prop.md) | NQ opening range breakout (presets A–E), everything tested on top of it, ES/BTC/gold, prop-firm and own-account simulations |
| [FINDINGS_bollinger.md](FINDINGS_bollinger.md) | Bollinger Band scalps, confluence filters and breakouts on BTC, NQ, ES, gold; BTC 60-minute breakout stress test |

## Headline results

1. **Preset E on MNQ** (London 07:30–08:30 breakout, 1 × 14-day average range stop, flat 15:55 NY):
   +$58.5k on 1 MNQ over 2020–26, −$7.2k worst drawdown, 7 of 7 years profitable. Best strategy found,
   **but it failed on untouched 2014–19 data** (−$2.1k, edge indistinguishable from zero): see the findings.
2. **BTC 60-minute Bollinger breakout** (3σ, stop trailed to middle band): real edge that passes stress
   tests **and its out-of-sample test on 2017–19** (+0.79%/trade, all nearby settings profitable). The most
   robust edge found, but decaying almost every year: 1.8% (2017) → 0.5% (2018–19) → 0.1% a trade (2025–26).
3. **Bollinger scalps / fades and 300+ ORB add-ons:** no edge after costs.
4. **Prop route:** with real Lucid / MyFundedFutures rules, Lucid Flex fits E best: $2.2k–6.5k/yr in 2020–26
   depending on size, but every plan loses (fees) if the edge is gone. MFFU Pro fits worst (news rule).
   No setup keeps a single funded account alive reliably.
5. **Slippage / Monte Carlo:** slippage is not the risk (break-even ~17 pts round trip in 2020–26). The risk is
   the edge itself: if it is weaker than 2020–26, 1 MNQ needs $15–20k to survive, and a year of results
   is weak evidence either way (a positive year happens 43% of the time even with no edge).

## TradingView scripts

- `nq_orb_strategy.pine`: ORB presets A, B, C, D, E (default), NY and Custom; entry/exit alerts and entry/SL/TP lines (TradingView version 5).
- `ibs_long_strategy.pine`: the TradingView IBS long rule with alerts (retired: the phone-app rule is better).
- `tv_fixed/`: fixed copies of the scripts that were on the "Unnamed" layout (see its README).
- `nq_bb_ema_strategy.pine`: NQ Bollinger + EMA200 strategy.
- `btc_bb_breakout.pine`: BTC 60-minute Bollinger breakout (use on a 1-hour BTC chart).
- `nq_orb_prop.pine`: preset E in Lucid prop mode (2 MNQ; $1,200 daily cap in the evaluation). See STRATEGIES.md, strategy 4.

## Re-running

Market data and result tables (`*.parquet`, `*.pkl`) are git-ignored. Re-download with `fetch_data.py`
and install `pandas numpy numba pyarrow` in a virtual environment.
