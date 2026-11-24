# Fixed TradingView scripts (2026-11-24)

Fixed copies of the scripts that were on the "Unnamed" MNQ1! 5-minute layout. Each one is saved in
TradingView under the name below, as a new script; the originals were left untouched.

| File | TradingView name | Original (script version on the chart) | What was wrong |
|---|---|---|---|
| `bb_breakout_trail_fixed.pine` | BB Breakout + TP/SL/Trail (fixed) | "BB Breakout Fixed No Trail" v35 | Trail given in price instead of ticks (5-pt trail on MNQ, $5 on BTC); plotted trail and alerts didn't match the real order; 150-tick slippage (37.5 pts per side on MNQ) |
| `bb_breakout_notrail_fixed.pine` | BB Breakout No Trail (fixed) | same script, v1 | No commission or slippage |
| `btc_4h_donchian_v7_fixed.pine` | BTC 4H Donchian Trend v7 (fixed) | "BTC 4h SFP+VOL" draft 0.7 | Fractional size on futures rounds to 0 contracts, so it never traded on MNQ; risk ignored the point value |
| `h4_fixed.pine` | H4 (fixed) | "BTC 4h SFP+VOL" draft 0.123 | Same sizing bug; 100-tick slippage (25 pts per side on MNQ); loop ran with no open trades; one leg's opposite entry closed the other legs |
| `nq_orb_combo_prop_fixed.pine` | NQ ORB combo (prop, fixed) | "ORB15 signals (TP/SL)" draft 0.4 | Loop ran with no open trades; $125 risk sized most setups to 0 contracts (new "take 1 micro" input, on by default) |

`../nq_orb_strategy.pine`: slippage raised from 1 to 2 ticks per side to match the research. The saved TradingView
copy (version 4) still has 1 tick; change it under the strategy's Properties → Slippage.

## TradingView backtests after the fix

| Script | MNQ1! 5m before | MNQ1! 5m after | BTCUSDT 4h after |
|---|---|---|---|
| BB + TP/SL/Trail | 33 trades, −$39,973 | 32 trades, −$13,880 | 794 trades, +$994,558, PF 1.17, max DD $480,966 (40% of equity per trade, compounding) |
| BB No Trail | 32 trades, +$1,987 (no costs) | 32 trades, −$911 | 735 trades, +$222,750, PF 1.12 |
| Donchian v7 | 0 trades | 0 trades: $10k can't buy 1 MNQ at 1% risk / 1x equity (counted in the table) | 247 trades, +$12,437, PF 1.96 |
| H4 | 0 trades | 0 trades: same reason | 1,538 trades, +$34,138, PF 1.70 |
| ORB combo (prop) | 1 trade, −$117 | 4 trades, +$14 | n/a |

Notes:
- The BB scripts use a 0.06% commission, which fits crypto. On MNQ the real cost is about $0.62 per contract per
  side, so on futures set Properties → Commission to "per contract, 0.62" — 0.06% of a $53k MNQ is ~$32.
- The ORB combo (prop) still trades rarely: the 75-point max stop now rules out most days at current NQ volatility.
  The "v4 r200" copy uses 100 points and takes about 4 times as many trades.
- TradingView history on a 5-minute chart is only a few months, so the MNQ figures are small samples.
