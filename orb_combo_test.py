"""NQ ORB combo (prop, fixed) vs ORB preset E, on the same 1-minute NQ data (2013-2026).

Combo, as in tv_fixed/nq_orb_combo_prop_fixed.pine (New York time, 5-minute bars):
  * ORB5: first 5-minute bar after 09:35 that closes outside the 09:30 bar's range; ORB15: same with 09:30-09:45.
    Opening Drive: at the 09:55 bar's close, move from the open >= 0.35 x the 09:30-10:00 range and >= 15 pts.
  * Only in the direction of the daily trend (yesterday's close vs its 50-day average).
  * Market entry at the next bar's open, stop at the other side of the range, target 3R, flat at 15:50.
  * Stop distance (from the signal close) 5-75 pts. Size: floor($125 / (stop x $2)), at least 1, at most 10.
  * No new entries once the day is down $350. (The script's "stop trading after $1,500 below peak" lock is left
    out: it would stop the backtest for good at the first $1,500 drawdown.)
Costs: 2 ticks slippage per side + $0.62 per contract per side.

Usage: python orb_combo_test.py nq_1m_2012_2026.parquet
"""
import sys

import numpy as np
import pandas as pd

import futures_test as f

PTV, SLIP, COMM = 2.0, 0.5, 0.62
RISK, MINR, MAXR, MAXQ, TGT, DLL = 125.0, 5.0, 75.0, 10, 3.0, 350.0


def five_min(path):
    df = pd.read_parquet(path).tz_convert("America/New_York")
    m = df.index.hour * 60 + df.index.minute
    df = df[(m >= 570) & (m < 960) & (df.index.day_of_week < 5)]
    b = df.resample("5min", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    b["day"] = b.index.normalize().tz_localize(None)
    b["mins"] = b.index.hour * 60 + b.index.minute - 570
    return b


def daily_trend(b, n=50):
    c = b.groupby("day").close.last()
    sma = c.rolling(n).mean()
    up = (c > sma).shift(1); dn = (c < sma).shift(1)
    return up, dn


def run(b, one_contract=False):
    up, dn = daily_trend(b)
    rows = []
    for day, g in b.groupby("day"):
        if g.mins.iloc[0] != 0 or len(g) < 70 or pd.isna(up.get(day)):
            continue
        O, H, L, C, M = (g[k].to_numpy() for k in ("open", "high", "low", "close", "mins"))
        dUp, dDn = bool(up[day]), bool(dn[day])
        hi5, lo5 = H[0], L[0]
        hi15, lo15 = H[M < 15].max(), L[M < 15].min()
        hi6, lo6 = H[M < 30].max(), L[M < 30].min()
        done = {"ORB5": False, "ORB15": False, "DRV": False}
        opens, day_pnl = [], 0.0          # open trades: dict(id, dir, entry, stop, tgt, qty)
        pending = []
        for i in range(len(g)):
            # fills of orders placed at the previous bar's close
            for p in pending:
                ep = O[i] + p["dir"] * SLIP
                R = abs(ep - p["stop"])
                p.update(entry=ep, tgt=ep + p["dir"] * TGT * R, i=i)
                opens.append(p)
            pending = []
            # exits inside this bar (stop first if both)
            still = []
            for t in opens:
                d = t["dir"]
                hit_s = (L[i] <= t["stop"]) if d > 0 else (H[i] >= t["stop"])
                hit_t = (H[i] >= t["tgt"]) if d > 0 else (L[i] <= t["tgt"])
                if hit_s or hit_t:
                    px = t["stop"] if hit_s else t["tgt"]
                    if hit_s:
                        px = min(px, O[i]) if d > 0 else max(px, O[i])          # gap through the stop
                    xp = px - d * SLIP
                    pnl = (xp - t["entry"]) * d * PTV * t["qty"] - 2 * COMM * t["qty"]
                    rows.append({"day": day, "id": t["id"], "dir": d, "qty": t["qty"], "pnl": pnl, "exit": "stop" if hit_s else "target"})
                    day_pnl += pnl
                else:
                    still.append(t)
            opens = still
            if M[i] >= 380:                                                       # 15:50 bar: flat at its open
                for t in opens:
                    xp = O[i] - t["dir"] * SLIP
                    pnl = (xp - t["entry"]) * t["dir"] * PTV * t["qty"] - 2 * COMM * t["qty"]
                    rows.append({"day": day, "id": t["id"], "dir": t["dir"], "qty": t["qty"], "pnl": pnl, "exit": "time"})
                break
            open_pnl = sum((C[i] - t["entry"]) * t["dir"] * PTV * t["qty"] for t in opens)
            locked = day_pnl + open_pnl <= -DLL
            live_ids = {t["id"] for t in opens}

            def try_entry(sid, d, stop):
                r = (C[i] - stop) * d
                if not ((d > 0 and dUp) or (d < 0 and dDn)) or r < MINR or r > MAXR or sid in live_ids:
                    return
                q = 1 if one_contract else min(MAXQ, max(1, int(RISK // (max(r, MINR) * PTV))))
                pending.append({"id": sid, "dir": d, "stop": stop, "qty": q})

            if locked:
                continue
            if not done["ORB5"] and M[i] >= 5:
                d = 1 if C[i] > hi5 else -1 if C[i] < lo5 else 0
                if d:
                    done["ORB5"] = True; try_entry("ORB5", d, lo5 if d > 0 else hi5)
            if not done["ORB15"] and M[i] >= 15:
                d = 1 if C[i] > hi15 else -1 if C[i] < lo15 else 0
                if d:
                    done["ORB15"] = True; try_entry("ORB15", d, lo15 if d > 0 else hi15)
            if not done["DRV"] and M[i] == 25:
                done["DRV"] = True
                mv = C[i] - O[0]; d = 1 if mv > 0 else -1
                if abs(mv) >= 0.35 * (hi6 - lo6) and abs(mv) >= 15:
                    try_entry("DRV", d, lo6 if d > 0 else hi6)
    return pd.DataFrame(rows)


def summary(daily, trades=None):
    eq = daily.cumsum(); yr = daily.groupby(daily.index.year).sum()
    out = {"net $": round(daily.sum()), "max DD $": round((eq.cummax() - eq).max()),
           "years > 0": f"{(yr > 0).sum()}/{len(yr)}", "2013-19 $": round(yr[yr.index < 2020].sum()),
           "2020-26 $": round(yr[yr.index >= 2020].sum()), "worst day $": round(daily.min()),
           "days traded": int((daily != 0).sum())}
    if trades is not None:
        out.update({"trades": len(trades), "win %": round((trades.pnl > 0).mean() * 100), "$/trade": round(trades.pnl.mean(), 1),
                    "avg contracts": round(trades.qty.mean(), 1)})
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    b = five_min(path)
    combo = run(b); combo1 = run(b, one_contract=True)
    e, _ = f.daily_pnl(path); e.index = e.index.tz_localize(None) if e.index.tz else e.index
    start = max(combo.day.min(), e.index.min()); end = min(combo.day.max(), e.index.max())
    cal = pd.bdate_range(start, end)
    dc = combo.groupby("day").pnl.sum().reindex(cal).fillna(0)
    dc1 = combo1.groupby("day").pnl.sum().reindex(cal).fillna(0)
    de = e.reindex(cal).fillna(0)
    pd.set_option("display.width", 220)
    print(f"{start.date()} -> {end.date()}\n")
    print(pd.DataFrame({"ORB E (1 MNQ)": summary(de), "Combo (script sizing)": summary(dc, combo[(combo.day >= start) & (combo.day <= end)]),
                        "Combo (1 MNQ/trade)": summary(dc1, combo1[(combo1.day >= start) & (combo1.day <= end)])}).to_string())
    c = combo[(combo.day >= start)]
    print("\nCombo by setup (script sizing):")
    print(c.groupby("id").agg(trades=("pnl", "size"), net=("pnl", "sum"), win=("pnl", lambda x: round((x > 0).mean() * 100)),
                              per_trade=("pnl", "mean")).round(0).to_string())
    print(f"\nDaily correlation E vs combo: {de.corr(dc):+.2f}")
    yr = pd.DataFrame({"E": de.groupby(de.index.year).sum(), "combo": dc.groupby(dc.index.year).sum(),
                       "combo 1 MNQ": dc1.groupby(dc1.index.year).sum()}).round(0)
    print("\nBy year:\n" + yr.to_string())


if __name__ == "__main__":
    main()
