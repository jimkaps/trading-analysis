"""Own account starting with $2,000, trading preset E (15:55 NY exit) on MNQ, vs the 50K prop cycle.

Rules for the own account:
  * You can only take a trade if equity covers the full stop for the contracts traded plus $100
    intraday margin per MNQ. Otherwise the account is "busted" (too small to trade the strategy).
  * If an open loss would take equity to zero or below, the account is wiped.
Scenarios:
  A  1 MNQ always, no top-up after a bust
  B  1 MNQ always, top up another $2,000 after each bust (like buying a new evaluation)
  C  compounding: 1 MNQ per $7,500 of equity (minimum 1), no top-up
  D  compounding as C, top up $2,000 after each bust
"""
import json

import numpy as np
import pandas as pd

import orb_sweep as s
import prop_lifecycle as pl
from prop_paths import path_block

START_CASH, MARGIN, PER_MNQ = 2000.0, 100.0, 7500.0

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
    pnl[sel] = p[sel] * 2 - 1.24; mae[sel] = a[sel] * 2 - 1.24
stop_usd = atr * 2.0 + 1.24     # full stop on 1 MNQ in $


def own(start, compounding, topup):
    eq = START_CASH; deposited = START_CASH; busts = 0; alive = True
    curve = np.zeros(len(pnl))
    for d in range(start, len(pnl)):
        p = pnl[d]
        if alive and p == p:
            n = max(1, int(eq // PER_MNQ)) if compounding else 1
            while n > 1 and eq < n * (stop_usd[d] + MARGIN):
                n -= 1
            if eq < n * (stop_usd[d] + MARGIN):
                alive = False
            elif eq + n * mae[d] <= 0:
                eq = 0.0; alive = False
            else:
                eq += n * p
            if not alive:
                busts += 1
                if topup:
                    eq += START_CASH; deposited += START_CASH; alive = True
                else:
                    eq = max(eq, 0.0)
        curve[d] = eq - deposited     # net profit = equity minus money put in
    curve[:start] = 0.0
    return curve, busts, deposited, eq


def prop(start, maxpay):
    pl.DD, pl.TGT, pl.CAP, pl.MIND, pl.FEE, pl.MAXPAY = 2000.0, 3000.0, 2000.0, 150.0, 150.0, maxpay
    c, ev = pl.lifecycle(pnl, mae, days, start, 2, 2)
    fees = sum(1 for e in ev if e[1] == "buy") * 150.0
    return c, fees


start = int(np.searchsorted(days, pd.Timestamp("2020-01-20")))
out = {}
rows = []
scen = {"A: 1 MNQ, no top-up": (False, False), "B: 1 MNQ, top up $2k after bust": (False, True),
        "C: compounding, no top-up": (True, False), "D: compounding, top up after bust": (True, True)}
for name, (comp, top) in scen.items():
    c, busts, dep, eq = own(start, comp, top)
    yr = pd.Series(np.diff(np.r_[0, c[start:]]), index=days[start:]).groupby(days[start:].year).sum()
    fin = []; bust_any = 0
    for m in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
        s0 = int(np.searchsorted(days, m))
        cc, b, dd, e2 = own(s0, comp, top)
        fin.append(cc[-1]); bust_any += b > 0
    rows.append({"scenario": name, "money put in": dep, "final equity": round(eq), "net profit": round(c[-1]),
                 "busts": busts, "worst dip": round((np.maximum.accumulate(c[start:]) - c[start:]).max()),
                 "starts that ever bust": f"{bust_any}/48", "net (median over 48 starts)": round(np.median(fin)),
                 **{str(y): round(v) for y, v in yr.items()}})
    out[name] = pd.Series(c[start:], index=days[start:]).resample("W-FRI").last().round(0).astype(int).tolist()
for name, cap in [("Prop 50K, 2 MNQ, max 6 payouts", 6), ("Prop 50K, 2 MNQ, unlimited payouts", 10 ** 9)]:
    c, fees = prop(start, cap)
    yr = pd.Series(np.diff(np.r_[0, c[start:]]), index=days[start:]).groupby(days[start:].year).sum()
    fin = [prop(int(np.searchsorted(days, m)), cap)[0][-1] for m in pd.date_range("2020-02-01", "2023-11-01", freq="MS")]
    rows.append({"scenario": name, "money put in": fees, "final equity": None, "net profit": round(c[-1]),
                 "busts": None, "worst dip": round((np.maximum.accumulate(c[start:]) - c[start:]).max()),
                 "starts that ever bust": "-", "net (median over 48 starts)": round(np.median(fin)),
                 **{str(y): round(v) for y, v in yr.items()}})
    out[name] = pd.Series(c[start:], index=days[start:]).resample("W-FRI").last().round(0).astype(int).tolist()
out["d"] = [x.strftime("%Y-%m-%d") for x in pd.Series(0, index=days[start:]).resample("W-FRI").last().index]
pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30)
print(pd.DataFrame(rows).to_string(index=False))
json.dump(out, open("own_vs_prop.json", "w"), separators=(",", ":"))
