"""Preset E with the 15:55 New York exit, run through the real-life 50K prop cycle
(buy $150 evaluation -> pass -> payouts -> bust -> buy again), Jan 2020 - Nov 2026.
Shows unlimited payouts and a 6-payouts-per-account cap, at 2 MNQ and at 2 MNQ eval / 1 MNQ funded.
"""
import json

import numpy as np
import pandas as pd

import orb_sweep as s
import prop_lifecycle as pl
from prop_paths import path_block

df = pd.read_parquet("nq_1m.parquet")
days, O, H, L, C = s.day_matrix(df, "Europe/London")
wk = days.weekday < 5
days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                       for d in days]).tz_convert("Europe/London")
exm = (ny.hour * 60 + ny.minute).to_numpy()
pnl = np.full(len(days), np.nan); mae = np.full(len(days), np.nan)
for ex in np.unique(exm):
    p, a, f = path_block(O, H, L, C, 450, 510, int(ex), atr, 1.0, 1.0)
    sel = exm == ex
    pnl[sel] = p[sel] * 2 - 1.24
    mae[sel] = a[sel] * 2 - 1.24
v = pd.Series(pnl, index=days).dropna()
print(f"Preset E (15:55 NY exit), 1 MNQ: total ${v.sum():,.0f}, trades {len(v)}")

pl.DD, pl.TGT, pl.CAP, pl.MIND, pl.FEE = 2000.0, 3000.0, 2000.0, 150.0, 150.0
start = int(np.searchsorted(days, pd.Timestamp("2020-01-20")))
out = {}
for label, ne, nf, cap in [("2 MNQ, unlimited payouts", 2, 2, 10 ** 9), ("2 MNQ, max 6 payouts per account", 2, 2, 6),
                           ("2 eval / 1 funded, unlimited", 2, 1, 10 ** 9), ("2 eval / 1 funded, max 6 payouts", 2, 1, 6)]:
    pl.MAXPAY = cap
    curve, events = pl.lifecycle(pnl, mae, days, start, ne, nf)
    e = pd.DataFrame(events, columns=["date", "kind", "amount"])
    e["year"] = pd.to_datetime(e.date).dt.year
    e["acct"] = (e.kind == "pass").cumsum()
    pay = e[e.kind == "payout"]
    yr = e.groupby("year").agg(bought=("kind", lambda k: (k == "buy").sum()), passed=("kind", lambda k: (k == "pass").sum()),
                               payouts=("kind", lambda k: (k == "payout").sum()),
                               paid=("amount", lambda a: a[a > 0].sum()), net=("amount", "sum"))
    yr["fees"] = -yr.bought * pl.FEE
    fin = []
    for m in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
        s0 = int(np.searchsorted(days, m))
        c, _ = pl.lifecycle(pnl, mae, days, s0, ne, nf)
        fin.append(c[-1] / ((len(pnl) - s0) / 252))
    print(f"\n===== 50K, {label} =====")
    print(f"Evaluations {int((e.kind == 'buy').sum())} (fees ${(e.kind == 'buy').sum() * pl.FEE:,.0f}), passed "
          f"{int((e.kind == 'pass').sum())} ({(e.kind == 'pass').sum() / (e.kind == 'buy').sum():.0%}), payouts {len(pay)} "
          f"totalling ${pay.amount.sum():,.0f}; NET ${e.amount.sum():,.0f}; net excl. 2026 ${e[e.year < 2026].amount.sum():,.0f}")
    print(f"Worst drop from a high ${(np.maximum.accumulate(curve[start:]) - curve[start:]).max():,.0f}; "
          f"biggest single account {pay.groupby('acct').amount.sum().max() / pay.amount.sum():.0%} of payouts; "
          f"net/yr across 48 start months: median ${np.median(fin):,.0f} (range ${min(fin):,.0f} to ${max(fin):,.0f})")
    print(yr[["bought", "passed", "payouts", "fees", "paid", "net"]].round(0).to_string())
    w = pd.Series(curve[start:], index=days[start:]).resample("W-FRI").last().dropna()
    out[label] = w.round(0).astype(int).tolist()
    out["d"] = [x.strftime("%Y-%m-%d") for x in w.index]
json.dump(out, open("prop_e_ny_50k.json", "w"), separators=(",", ":"))
