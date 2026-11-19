"""Check the $-cap skip rule for price drift, and test a stationary version: skip when the 14-day average
daily range is above X% of price. Same survival simulator as survive_search.py."""
import numpy as np
import pandas as pd

import orb_sweep as s
from prop_paths import path_block
from survive_search import run, ACCTS

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)

df = pd.read_parquet("nq_1m.parquet")
days, O, H, L, C = s.day_matrix(df, "Europe/London")
wk = days.weekday < 5
days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
px = C[:, 509]
atr_pct = atr / px * 100
years = days.year.to_numpy()
starts = np.array([i for i in range(15, len(days) - 30, 5) if years[i] <= 2025])
sy = years[starts]

p, a, f = path_block(O, H, L, C, 450, 510, 1255, atr, 1.0, 1.0)
pnl0 = p * 2.0 - 1.24; mae0 = a * 2.0 - 1.24
traded = ~np.isnan(pnl0)
print("Trades per year with the '$600 cap' rule vs all trades:")
cap = atr * 2.0 <= 600
print(pd.DataFrame({"all": pd.Series(traded).groupby(years).sum(),
                    "$600 cap": pd.Series(traded & cap).groupby(years).sum(),
                    "median stop $": pd.Series(atr * 2).groupby(years).median().round(0)}).T.to_string())
print(f"\nToday (Nov 2026): stop ~${atr[-1] * 2:,.0f} per MNQ, ATR = {atr_pct[-1]:.2f}% of price")
print("ATR % of price, percentiles 2020-2026: " + ", ".join(f"p{q}={np.nanpercentile(atr_pct, q):.2f}%" for q in (25, 50, 75, 90)))

rows = []
for x in (np.inf, 2.5, 2.0, 1.8, 1.6, 1.4, 1.2):
    keep = ~(atr_pct > x)
    pnl = np.where(keep, pnl0, np.nan); mae = np.where(keep, mae0, np.nan)
    v = pnl[~np.isnan(pnl)]; eq = np.cumsum(v); mdd = (np.maximum.accumulate(eq) - eq).max()
    tby = pd.Series(~np.isnan(pnl)).groupby(years).sum()
    for acct, (dd, tgt, cp) in ACCTS.items():
        for ne in range(1, 7):
            for nf in range(1, min(ne, 3) + 1):
                o = run(pnl, mae, starts, ne, nf, dd, tgt, cp)
                ok = (o[:, 0] == 1) & (o[:, 2] >= 252)
                by = [ok[sy == y].mean() * 100 for y in range(2020, 2026)]
                rows.append({"skip if ATR >% of price": x, "account": acct, "eval MNQ": ne, "funded MNQ": nf,
                             "pass %": (o[:, 0] == 1).mean() * 100, "survive 1yr %": ok.mean() * 100,
                             "worst start-yr %": min(by), "payouts in yr $": o[ok, 3].mean() if ok.any() else 0,
                             "1-MNQ total $": v.sum(), "1-MNQ maxDD $": mdd, "trades 2026": tby.get(2026, 0),
                             **{f"s{y}": b for y, b in zip(range(2020, 2026), by)}})
r = pd.DataFrame(rows)
num = [c for c in r.columns if c not in ("skip if ATR >% of price", "account", "eval MNQ", "funded MNQ")]
r[num] = r[num].round(0)
print("\nTop 20 by 1-year survival (stationary %-of-price skip rule):")
print(r.sort_values("survive 1yr %", ascending=False).head(20).to_string(index=False))
