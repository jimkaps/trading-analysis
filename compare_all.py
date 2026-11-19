"""Everything side by side, real-life sequence Jan 2020 - Nov 2026, 6-payout cap per funded account.

Strategies:  E  = 07:30-08:30 London range, no TP, stop 1 x ATR14, exit 15:55 New York
             A  = your original: 07:30-08:20 London range, TP 205 pts, SL 211 pts, exit 16:00 London
Ways to trade them: prop 50K ($150/eval), prop 150K ($350/eval), own account starting with $2,000.
"""
import json

import numpy as np
import pandas as pd

import orb_sweep as s
import prop_lifecycle as pl
from prop_paths import path_block
from prop_search import block

df = pd.read_parquet("nq_1m.parquet")
days, O, H, L, C = s.day_matrix(df, "Europe/London")
wk = days.weekday < 5
days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()

# E with 15:55 NY exit
ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                       for d in days]).tz_convert("Europe/London")
exm = (ny.hour * 60 + ny.minute).to_numpy()
E_p = np.full(len(days), np.nan); E_m = np.full(len(days), np.nan)
for ex in np.unique(exm):
    p, a, f = path_block(O, H, L, C, 450, 510, int(ex), atr, 1.0, 1.0)
    sel = exm == ex
    E_p[sel] = p[sel] * 2 - 1.24; E_m[sel] = a[sel] * 2 - 1.24
E_stop = atr * 2 + 3.24
# A: points TP/SL via the ATR-multiple engine with "ATR" = 1 point
ones = np.where(np.isnan(atr), np.nan, 1.0)
p, m = block(O, H, L, C, 450, 500, np.array([960]), ones, np.array([205.0]), np.array([211.0]), 1.0)
A_p = p[:, 0, 0, 0].astype(float) * 2 - 1.24; A_m = m[:, 0, 0, 0].astype(float) * 2 - 1.24
A_stop = np.full(len(days), 211 * 2 + 3.24)
for nm, v in (("E", E_p), ("A", A_p)):
    vv = pd.Series(v, index=days).dropna(); eq = vv.cumsum()
    print(f"{nm} 1 MNQ: total ${vv.sum():,.0f}, max DD ${(eq.cummax() - eq).max():,.0f}, win {(vv > 0).mean():.0%}, trades {len(vv)}")

ACCT = {"50K": (2000.0, 3000.0, 2000.0, 150.0, 150.0), "150K": (4500.0, 9000.0, 5000.0, 250.0, 350.0)}


def prop(pnl, mae, acct, ne, nf, start, maxpay=6):
    pl.DD, pl.TGT, pl.CAP, pl.MIND, pl.FEE = ACCT[acct]; pl.MAXPAY = maxpay
    c, ev = pl.lifecycle(pnl, mae, days, start, ne, nf)
    e = pd.DataFrame(ev, columns=["date", "kind", "amount"])
    return c, {"evals": int((e.kind == "buy").sum()), "passes": int((e.kind == "pass").sum()),
               "payouts": int((e.kind == "payout").sum()), "money in": float((e.kind == "buy").sum() * pl.FEE)}


def own(pnl, mae, stop, start, cash=2000.0, topup=True):
    eq = cash; dep = cash; busts = 0
    c = np.zeros(len(pnl))
    for d in range(start, len(pnl)):
        p = pnl[d]
        if p == p:
            if eq < stop[d] + 100 or eq + mae[d] <= 0:
                busts += 1
                eq = max(eq + (mae[d] if eq + mae[d] > 0 else -eq), 0.0) if eq >= stop[d] + 100 else eq
                if topup:
                    eq += cash; dep += cash
            else:
                eq += p
        c[d] = eq - dep
    c[:start] = 0.0
    return c, {"evals": None, "passes": None, "payouts": None, "money in": dep, "busts": busts}


OPTS = [  # label, kind, strategy, args
    ("E | prop 150K, eval 5 / funded 2 MNQ", "prop", "E", ("150K", 5, 2)),
    ("E | prop 150K, 5 MNQ throughout", "prop", "E", ("150K", 5, 5)),
    ("E | prop 50K, 2 MNQ throughout", "prop", "E", ("50K", 2, 2)),
    ("E | prop 50K, eval 2 / funded 1 MNQ", "prop", "E", ("50K", 2, 1)),
    ("E | own account $2k, 1 MNQ (top up $2k if busted)", "own", "E", ()),
    ("A | prop 150K, eval 5 / funded 2 MNQ", "prop", "A", ("150K", 5, 2)),
    ("A | prop 50K, 2 MNQ throughout", "prop", "A", ("50K", 2, 2)),
    ("A | own account $2k, 1 MNQ (top up $2k if busted)", "own", "A", ()),
]
DATA = {"E": (E_p, E_m, E_stop), "A": (A_p, A_m, A_stop)}
start = int(np.searchsorted(days, pd.Timestamp("2020-01-20")))
i26 = int(np.searchsorted(days, pd.Timestamp("2026-01-01")))
rows = []; curves = {}
for label, kind, strat, args in OPTS:
    pnl, mae, stop = DATA[strat]
    run = (lambda st: prop(pnl, mae, *args, st)) if kind == "prop" else (lambda st: own(pnl, mae, stop, st))
    c, info = run(start)
    yr = pd.Series(np.diff(np.r_[0, c[start:]]), index=days[start:]).groupby(days[start:].year).sum()
    fin = []
    for mth in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
        s0 = int(np.searchsorted(days, mth)); cc, _ = run(s0)
        fin.append(cc[i26 - 1] / ((i26 - s0) / 252))        # per year, to end of 2025
    rows.append({"option": label, **info, "net Nov-2026": round(c[-1]), "net to end-2025": round(c[i26 - 1]),
                 "worst dip": round((np.maximum.accumulate(c[start:]) - c[start:]).max()),
                 "net/yr 2020-25 (median start)": round(np.median(fin)), "worst start": round(min(fin)),
                 "years+ 2020-25": int((yr.loc[2020:2025] > 0).sum()),
                 **{str(y): round(v) for y, v in yr.items()}})
    curves[label] = pd.Series(c[start:], index=days[start:]).resample("W-FRI").last().round(0).astype(int).tolist()
curves["d"] = [x.strftime("%Y-%m-%d") for x in pd.Series(0, index=days[start:]).resample("W-FRI").last().index]
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30)
print(pd.DataFrame(rows).to_string(index=False))
json.dump(curves, open("compare_all.json", "w"), separators=(",", ":"))
