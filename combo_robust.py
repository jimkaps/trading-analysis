"""Robustness: 50K, NQ_E x1 + NY-open leg x5, 6-payout cap, $150 fee - with 162 nearby NY settings.
Also runs the chosen combo through 2026 and a 150K version.
"""
import itertools

import numpy as np
import pandas as pd

import orb_sweep as s
import prop_lifecycle as pl
from prop_search import block

st = pd.read_parquet("streams.parquet").fillna(0.0)
df = pd.read_parquet("nq_1m.parquet")
days, O, H, L, C = s.day_matrix(df, "America/New_York")
wk = days.weekday < 5
days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()


def cycle(pnl_e, mae_e, ny_p, ny_m, ne, nn, dates, end, acct="50K"):
    if acct == "50K":
        pl.DD, pl.TGT, pl.CAP, pl.MIND, pl.FEE = 2000.0, 3000.0, 2000.0, 150.0, 150.0
    else:
        pl.DD, pl.TGT, pl.CAP, pl.MIND, pl.FEE = 4500.0, 9000.0, 5000.0, 250.0, 350.0
    pl.MAXPAY = 6
    m = dates <= end
    p = pnl_e[m] * ne + ny_p[m] * nn
    a = np.minimum(mae_e[m], 0) * ne + np.minimum(ny_m[m], 0) * nn
    traded = (pnl_e[m] != 0) | (ny_p[m] != 0)
    p = np.where(traded, p, np.nan)
    d = dates[m]
    fin = []
    for mo in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
        s0 = int(np.searchsorted(d, mo))
        c, _ = pl.lifecycle(p, a, d, s0, 1, 1)
        fin.append(c[-1] / ((len(p) - s0) / 252))
    c, ev = pl.lifecycle(p, a, d, int(np.searchsorted(d, pd.Timestamp("2020-01-20"))), 1, 1)
    e = pd.DataFrame(ev, columns=["date", "kind", "amount"]); e["year"] = pd.to_datetime(e.date).dt.year
    yr = e.groupby("year").amount.sum()
    return np.median(fin), np.min(fin), yr, e, c


# align NY results (indexed by NY date) to the stream index (London date) - same calendar dates on weekdays
idx = st.index
pe, me = st["NQ_E_pnl"].to_numpy(), st["NQ_E_mae"].to_numpy()
rows = []
for rs, ln, tp, sl, ex in itertools.product([585, 600, 615], [15, 30, 45], [0.4, 0.5, 0.7], [0.15, 0.2, 0.3], [900, 955]):
    p, m = block(O, H, L, C, rs, rs + ln, np.array([ex]), atr, np.array([tp]), np.array([sl]), 1.0)
    sp = pd.Series(p[:, 0, 0, 0].astype(float) * 2 - 1.24, index=days).reindex(idx).fillna(0).to_numpy()
    sm = pd.Series(m[:, 0, 0, 0].astype(float) * 2 - 1.24, index=days).reindex(idx).fillna(0).to_numpy()
    med, worst, yr, _, _ = cycle(pe, me, sp, sm, 1, 5, idx, pd.Timestamp("2025-12-31"))
    _, _, yr26, _, _ = cycle(pe, me, sp, sm, 1, 5, idx, pd.Timestamp("2026-12-31"))
    rows.append({"start": rs, "len": ln, "tp": tp, "sl": sl, "exit": ex, "net/yr median": med, "worst start": worst,
                 "yrs+ 2020-25": int((yr > 0).sum()), "worst yr": yr.min(), "2026": yr26.get(2026, 0.0)})
r = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print(f"162 nearby NY settings, 50K, E x1 + NY x5, cap 6:")
print(f"  net/yr (2020-25) median across settings ${r['net/yr median'].median():,.0f}; "
      f"{(r['net/yr median'] > 0).mean():.0%} positive; 25th pct ${r['net/yr median'].quantile(.25):,.0f}")
print(f"  settings with all 6 years positive: {(r['yrs+ 2020-25'] == 6).mean():.0%}; >=5 years: {(r['yrs+ 2020-25'] >= 5).mean():.0%}")
print(f"  2026 net: median ${r['2026'].median():,.0f}, positive in {(r['2026'] > 0).mean():.0%} of settings")
print("  by parameter (median net/yr):")
for c in ["start", "len", "tp", "sl", "exit"]:
    print("   ", c, r.groupby(c)["net/yr median"].median().round(0).to_dict())

# chosen combo, through 2026, both accounts
for acct, ne, nn in [("50K", 1, 5), ("150K", 2, 10), ("150K", 3, 8)]:
    med, worst, yr, e, c = cycle(pe, me, st["NQ_NY_pnl"].to_numpy(), st["NQ_NY_mae"].to_numpy(), ne, nn, idx,
                                 pd.Timestamp("2026-12-31"), acct)
    print(f"\n{acct} E x{ne} + NY x{nn} through Nov 2026: evals {(e.kind == 'buy').sum()}, passes {(e.kind == 'pass').sum()}, "
          f"payouts {(e.kind == 'payout').sum()}, net ${e.amount.sum():,.0f}; worst dip ${(np.maximum.accumulate(c) - c).max():,.0f}")
    print("   yearly:", {int(k): round(v) for k, v in yr.items()})
