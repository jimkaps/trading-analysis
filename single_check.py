"""Corrected single-account check for top candidates: an account still alive when the data ends counts as surviving."""
import numpy as np
import pandas as pd

import orb_sweep as s
from prop_search import block
from single_acct import sim

CANDS = [  # (label, anchor tz, start, len, exit, tp, sl, acct, MNQ)
    ("E (current), 50K x1", "Europe/London", 450, 60, 1255, 99.0, 1.0, "50K", 1),
    ("E (current), 50K x2", "Europe/London", 450, 60, 1255, 99.0, 1.0, "50K", 2),
    ("E, 150K x2", "Europe/London", 450, 60, 1255, 99.0, 1.0, "150K", 2),
    ("NY 09:30-10:30, no TP, stop 0.15xATR, 50K x1", "America/New_York", 570, 60, 955, 99.0, 0.15, "50K", 1),
    ("NY 09:45-09:50, no TP, stop 0.15xATR, 50K x1", "America/New_York", 585, 5, 955, 99.0, 0.15, "50K", 1),
    ("Lon 07:15-07:45, no TP, stop 0.15xATR, exit 16:00, 50K x1", "Europe/London", 435, 30, 960, 99.0, 0.15, "50K", 1),
    ("NY 09:30-10:30, no TP, stop 0.15xATR, 150K x2", "America/New_York", 570, 60, 955, 99.0, 0.15, "150K", 2),
]
ACCTS = {"50K": (2000.0, 3000.0, 2000.0, 150.0, 150.0), "150K": (4500.0, 9000.0, 5000.0, 250.0, 350.0)}
df = pd.read_parquet("nq_1m.parquet")
cache = {}
rows = []
for label, tz, rs_, ln, ex, tp, sl, acct, n in CANDS:
    if tz not in cache:
        days, O, H, L, C = s.day_matrix(df, tz)
        wk = days.weekday < 5
        days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
        rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
        atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
        cache[tz] = (days, O, H, L, C, atr)
    days, O, H, L, C, atr = cache[tz]
    p, m = block(O, H, L, C, rs_, rs_ + ln, np.array([ex]), atr, np.array([tp]), np.array([sl]), 1.0)
    pv = p[:, 0, 0, 0].astype(float) * 2 - 1.24; mv = m[:, 0, 0, 0].astype(float) * 2 - 1.24
    dd, tgt, cap, mind, fee = ACCTS[acct]
    st = np.arange(20, len(days) - 60, 5)
    out = sim(pv, mv, st, n, dd, tgt, cap, mind)
    passed = out[:, 0] == 1
    reached_end = st + out[:, 1] + out[:, 2] >= len(days) - 1
    survived = passed & ((out[:, 2] >= 252) | reached_end)
    yrs = days[st].year
    row = {"setup": label, "pass": passed.mean(), "pass+survive 1yr": survived.mean(),
           "alive 6m": (passed & ((out[:, 2] >= 126) | reached_end)).mean(),
           "median days to pass": np.median(out[passed, 1]), "avg payouts - fee": out[:, 3].mean() - fee}
    for y in range(2020, 2027):
        row[f"surv {y}"] = survived[yrs == y].mean() if (yrs == y).any() else np.nan
    rows.append(row)
pd.set_option("display.width", 280); pd.set_option("display.max_columns", 30)
print(pd.DataFrame(rows).round(2).to_string(index=False))
