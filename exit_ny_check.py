"""Preset E with exit at 15:55 New York (instead of 20:55 London) - impact on the backtest."""
import numpy as np
import pandas as pd

import orb_sweep as s
from extra_test import gen_block

df = pd.read_parquet("nq_1m.parquet")
days, O, H, L, C = s.day_matrix(df, "Europe/London")
wk = days.weekday < 5
days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
# London minute of 15:55 New York on each day
ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                       for d in days]).tz_convert("Europe/London")
exm = (ny.hour * 60 + ny.minute).to_numpy()
res = {}
for ex in np.unique(exm):
    p = gen_block(O, H, L, C, 450, 510, int(ex), 0.0, 0, atr, 1.0, 0.0, 0, 1.0)
    res[ex] = p * 2 - 1.24
new = np.array([res[e][i] for i, e in enumerate(exm)])
old = gen_block(O, H, L, C, 450, 510, 1255, 0.0, 0, atr, 1.0, 0.0, 0, 1.0) * 2 - 1.24
a = pd.Series(old, index=days).dropna(); b = pd.Series(new, index=days).dropna()
diff_days = (exm != 1255).sum()
print(f"Days where 15:55 NY is not 20:55 London: {diff_days} of {len(days)} ({diff_days / len(days) * 6.9 / 6.9:.1%}); "
      f"London exit on those days: {sorted(set(exm[exm != 1255]))} minutes")
for lab, v in [("20:55 London", a), ("15:55 New York", b)]:
    eq = v.cumsum(); yr = v.groupby(v.index.year).sum()
    print(f"{lab:15s} total ${v.sum():,.0f}  maxDD ${(eq.cummax() - eq).max():,.0f}  win {(v > 0).mean():.0%}  "
          f"years+ {(yr > 0).sum()}/7  " + " ".join(f"{y}:{x:,.0f}" for y, x in yr.items()))
