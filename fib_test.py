"""Fibonacci retracement entries for the morning ORB, compared with the plain breakout entry (preset D style).

After the first breakout of the opening range, place a limit order at a fib retracement:
  mode "range"  : fib of the opening range itself, e.g. long at  high - f * (high - low)
  mode "impulse": fib of the move from the range's far side to the running extreme since the
                  breakout, e.g. long at  swing_high - f * (swing_high - range_low)  (no look-ahead:
                  the swing uses bars before the fill bar)
Order expires at a cut-off time; no fill = no trade that day. Stops: opposite side of the range,
or a fixed % from entry. Exit: optional 2% target, otherwise flat at the exit time.

Judged on 18 settings around D (start 07:15/07:30/07:45, range 45/60/90 min, exit 19:30/20:55),
per period, against the breakout entry with the same range, exit and a 1% stop.

Usage: python fib_test.py nq_1m.parquet
"""
import sys

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)

STARTS = [435, 450, 465]
LENS = [45, 60, 90]
EXITS = [1170, 1255]
FIBS = [0.236, 0.382, 0.5, 0.618, 0.786]
MODES = {0: "range", 1: "impulse"}
STOPS = {0: "range far side", 1: "1% fixed", 2: "0.5% fixed"}
EXPIRY = {0: "2h after range", 1: "14:30 (US open)", 2: "exit time"}
TPS = {0: "none", 1: "2%"}
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
YRS = list(range(2020, 2027))


@njit
def fib_block(O, H, L, C, rs, re_, ex, mode, f, stop_mode, exp_min, tp_mode, cost_pts):
    nd = O.shape[0]
    out = np.full(nd, np.nan)
    for d in range(nd):
        rh = -1e18; rl = 1e18; nbar = 0; nflat = 0
        for m in range(rs, re_):
            h = H[d, m]
            if h == h:
                nbar += 1
                if h > rh: rh = h
                if L[d, m] < rl: rl = L[d, m]
                if h == L[d, m]: nflat += 1
        if nbar < (re_ - rs) * 0.8 or nflat > nbar * 0.5 or rh <= rl:
            continue
        w = rh - rl
        # breakout side (same rule as the breakout engine)
        bo = -1; side = 0
        for m in range(re_, ex):
            h = H[d, m]
            if h != h:
                continue
            up = h >= rh; dn = L[d, m] <= rl
            if up or dn:
                o = O[d, m]
                if o >= rh: side = 1
                elif o <= rl: side = -1
                elif up and dn: side = 1 if rh - o <= o - rl else -1
                elif up: side = 1
                else: side = -1
                bo = m
                break
        if bo < 0:
            continue
        # signed-space helpers: work as if long
        swing = (H[d, bo] if side == 1 else -L[d, bo])
        far = rl if side == 1 else -rh          # range far side in signed space
        near = rh if side == 1 else -rl
        last_entry = min(exp_min, ex)
        ent = -1; px = 0.0
        for m in range(bo + 1, last_entry):
            h = H[d, m]
            if h != h:
                continue
            if mode == 0:
                lvl = near - f * w
            else:
                lvl = swing - f * (swing - far)
            lo_s = L[d, m] if side == 1 else -h
            o_s = O[d, m] if side == 1 else -O[d, m]
            if lo_s <= lvl:
                px = o_s if o_s < lvl else lvl
                ent = m
                break
            hi_s = h if side == 1 else -L[d, m]
            if hi_s > swing: swing = hi_s
        if ent < 0:
            continue
        if stop_mode == 0:
            sl = far
        elif stop_mode == 1:
            sl = px - abs(px) * 0.01
        else:
            sl = px - abs(px) * 0.005
        if sl >= px:
            continue
        tp = px + abs(px) * 0.02 if tp_mode == 1 else 1e18
        res = np.nan; lastc = px
        for m in range(ent, ex):
            h = H[d, m]
            if h != h:
                continue
            hi_s = h if side == 1 else -L[d, m]
            lo_s = L[d, m] if side == 1 else -h
            lastc = C[d, m] if side == 1 else -C[d, m]
            if lo_s <= sl:
                res = sl - px; break
            if m > ent and hi_s >= tp:
                res = tp - px; break
        if res != res:
            res = lastc - px
        out[d] = res - cost_pts
    return out


def stats(v, years):
    traded = ~np.isnan(v)
    x = np.where(traded, v, 0.0)
    eq = np.cumsum(x)
    d = {"trades": int(traded.sum()), "wins": int((x > 0).sum()), "maxdd": (np.maximum.accumulate(eq) - eq).max(),
         "total": x.sum()}
    for y in YRS:
        d[y] = x[years == y].sum()
    return d


def main():
    df = pd.read_parquet(sys.argv[1])
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    years = days.year.to_numpy()
    rows = []
    for rs in STARTS:
        for ln in LENS:
            re_ = rs + ln
            pnl, dirs, *_ = s.run_block_full(O, H, L, C, rs, re_, np.array(EXITS), np.array([0]), np.array([99.0]),
                                             np.array([0]), np.array([1.0]), s.COST_PTS)
            for ei, ex in enumerate(EXITS):
                key = (rs, ln, ex)
                v = pnl[:, ei, 0, 0].astype(float) * s.PT_VALUE - s.COMMISSION
                rows.append({"setting": key, "entry": "BREAKOUT (D-style, 1% stop)", **stats(v, years)})
                for mode, mname in MODES.items():
                    for f in FIBS:
                        for sm, sname in STOPS.items():
                            for xm, xname in EXPIRY.items():
                                exp_min = {0: re_ + 120, 1: 870, 2: ex}[xm]
                                if exp_min <= re_:
                                    continue
                                for tm, tname in TPS.items():
                                    p = fib_block(O, H, L, C, rs, re_, ex, mode, f, sm, exp_min, tm, s.COST_PTS)
                                    v = p * s.PT_VALUE - s.COMMISSION
                                    rows.append({"setting": key,
                                                 "entry": f"{mname} fib {f} | stop {sname} | expires {xname} | TP {tname}",
                                                 **stats(v, years)})
        print(f"start {rs // 60:02d}:{rs % 60:02d} done", flush=True)
    r = pd.DataFrame(rows)
    for p, ys in PERIODS.items():
        r[p] = r[list(ys)].sum(axis=1)
    r["ret_dd"] = r.total / r.maxdd.clip(lower=1)
    base = r[r.entry.str.startswith("BREAKOUT")].set_index("setting")
    out = []
    for name, g in r.groupby("entry"):
        g = g.set_index("setting"); b = base.loc[g.index]
        row = {"entry": name, "trades/yr": round(g.trades.mean() / 6.9), "win%": round(100 * g.wins.sum() / max(g.trades.sum(), 1)),
               "mean total": round(g.total.mean()), "mean maxDD": round(g.maxdd.mean()), "ret/DD": round(g.ret_dd.mean(), 2)}
        ok = True
        for p in PERIODS:
            dlt = g[p] - b[p]
            row[f"{p} vs BO"] = round(dlt.mean())
            row[f"{p} %beat"] = f"{(dlt > 0).mean():.0%}"
            ok &= (dlt > 0).mean() >= 0.6
        row["yrs>0"] = f"{(g[YRS].mean() > 0).sum()}/7"
        row["PASS"] = "YES" if ok else ""
        out.append(row)
    res = pd.DataFrame(out).sort_values("ret/DD", ascending=False)
    print(f"\n{len(res) - 1} fib variants, each averaged over 18 settings around D. 'vs BO' = $ change vs breakout entry.")
    print(res.head(30).to_string(index=False))
    print(f"\nFib variants that beat the breakout in all three periods (>=60% of settings): {(res.PASS == 'YES').sum()}")
    print(f"Fib variants with higher mean total than breakout: {(res['mean total'] > res.loc[res.entry.str.startswith('BREAKOUT'), 'mean total'].iloc[0]).sum()}")
    by = r[~r.entry.str.startswith("BREAKOUT")].copy()
    by["fib"] = by.entry.str.extract(r"fib ([\d.]+)")[0]
    by["mode"] = by.entry.str.split(" ").str[0]
    print("\nMean total by fib level and mode (all stops/expiries/targets):")
    print(by.pivot_table(index="fib", columns="mode", values="total", aggfunc="mean").round(0).to_string())
    r.to_pickle("fib_rows.pkl")


if __name__ == "__main__":
    main()
