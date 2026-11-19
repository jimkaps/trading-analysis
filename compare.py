"""Run named setups exactly and print year-by-year results. Kind: 0=% 3=points."""
import sys

import numpy as np
import pandas as pd

import orb_sweep as s

SETUPS = {
    # name: (tz, start, end, exit, tp_kind, tp, sl_kind, sl)
    "A yours (pts)": ("Europe/London", 450, 500, 960, 3, 205.0, 3, 211.0),
    "B": ("Europe/London", 450, 500, 1260, 0, 1.5, 0, 0.5),
    "C": ("Europe/London", 900, 930, 1110, 0, 1.0, 0, 1.0),
    "D new": ("Europe/London", 450, 510, 1255, 0, 99.0, 0, 1.0),
}
df = pd.read_parquet(sys.argv[1])
rows = {}
cache = {}
for name, (tz, rs, re_, ex, tk, tv, sk, sv) in SETUPS.items():
    if tz not in cache:
        cache[tz] = s.day_matrix(df, tz)
    days, O, H, L, C = cache[tz]
    p, d, w, ref = s.run_block(O, H, L, C, rs, re_, np.array([ex]), np.array([tk]), np.array([tv]),
                               np.array([sk]), np.array([sv]), s.COST_PTS)
    usd = pd.Series(p[:, 0, 0, 0].astype(float) * s.PT_VALUE - s.COMMISSION, index=days).dropna()
    eq = usd.cumsum()
    yr = usd.groupby(usd.index.year).sum()
    rows[name] = {**{str(y): round(v) for y, v in yr.items()}, "Total": round(usd.sum()),
                  "MaxDD": round((eq.cummax() - eq).max()), "Win%": round((usd > 0).mean() * 100),
                  "Trades": len(usd), "PosYrs": f"{(yr > 0).sum()}/{len(yr)}",
                  "Aug-Nov26": round(usd[usd.index >= "2026-08-03"].sum())}
print(pd.DataFrame(rows).to_string())
