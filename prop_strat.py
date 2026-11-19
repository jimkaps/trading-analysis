"""Strategies designed for prop-firm rules (small fixed losses, frequent small wins, capped days), MNQ.

Families (one position at a time, several trades a day allowed, all distances in x 14-day average daily range):
  0 ORB scalp     : stop entries at the opening-range high/low; TP tpm, SL slm; re-arm a side after price
                    returns inside the range; up to K trades a day.
  1 Failed-break  : price breaks the range, then a 1-minute bar closes back inside within p1 minutes -> fade it.
                    SL = breakout extreme + slm; TP: p2=0 range middle, p2=1 far side of range, p2=2 tpm.
  2 Extension fade: from the anchor open, fade a move of p1 x ATR (limit); TP tpm (p2=1: back to the anchor),
                    SL slm. Each side once a day.
Daily caps: stop for the day when closed+open P&L <= -dl x ATR or closed P&L >= dt x ATR (0 = off).
Costs per trade: 1 pt slippage + $1.24 commission (1 MNQ, $2/pt).

Survival test (same as survive_search): one evaluation (EOD trailing DD checked vs open loss, target,
best day <= 50%, pass within 252 days), then funded for 252 days with payouts. Starts every 5 trading days.
Selection on 2020-2023 starts (IS), check on 2024-2025 starts (OOS).

Usage: python prop_strat.py
"""
import time

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s

pd.set_option("display.width", 260)
pd.set_option("display.max_rows", 200)
pd.set_option("display.max_columns", 40)
PTV, COST, COMM = 2.0, 1.0, 1.24
COSTP = COST + COMM / PTV          # all-in cost in points per trade


@njit
def family(O, H, L, C, atr, mode, rs, re_, ex, p1, p2, tpm, slm, K, dl, dt, cost):
    nd = O.shape[0]
    pnl = np.full(nd, np.nan); mae = np.full(nd, np.nan); ntr = np.zeros(nd)
    for d in range(nd):
        A = atr[d]
        if A != A or A <= 0:
            continue
        rh = -1e18; rl = 1e18; nbar = 0
        if mode != 2:
            for m in range(rs, re_):
                h = H[d, m]
                if h == h:
                    nbar += 1
                    if h > rh: rh = h
                    if L[d, m] < rl: rl = L[d, m]
            if nbar < (re_ - rs) * 0.8 or rh <= rl:
                continue
            start = re_
        else:
            anchor = O[d, rs]
            if anchor != anchor:
                continue
            start = rs + 1
        real = 0.0; worst = 0.0; trades = 0; pos = 0; ent = 0.0; tp = 0.0; sl = 0.0; done = False
        armL = True; armS = True
        bo = 0; bo_t = 0; ext = 0.0      # failed-break state: bo=+1 broke up, -1 broke down
        lastc = np.nan
        for m in range(start, ex):
            h = H[d, m]
            if h != h:
                continue
            o = O[d, m]; lo = L[d, m]; c = C[d, m]; lastc = c
            newpos = False
            # ---------------- entries ----------------
            if pos == 0 and not done and trades < K:
                if mode == 0:
                    a = armL and h >= rh; b = armS and lo <= rl
                    if a and b:
                        if rh - o <= o - rl: b = False
                        else: a = False
                    if a:
                        pos = 1; ent = max(o, rh); tp = ent + tpm * A; sl = ent - slm * A; armL = False
                    elif b:
                        pos = -1; ent = min(o, rl); tp = ent - tpm * A; sl = ent + slm * A; armS = False
                elif mode == 1:
                    if bo == 0:
                        if h >= rh and lo > rl: bo = 1; bo_t = m; ext = h
                        elif lo <= rl and h < rh: bo = -1; bo_t = m; ext = lo
                    else:
                        if bo == 1:
                            if h > ext: ext = h
                            if m - bo_t > p1: bo = 0
                            elif c < rh and m > bo_t:
                                pos = -1; ent = c; sl = ext + slm * A
                                tp = (rh + rl) / 2 if p2 == 0 else (rl if p2 == 1 else ent - tpm * A)
                                bo = 0
                        else:
                            if lo < ext: ext = lo
                            if m - bo_t > p1: bo = 0
                            elif c > rl and m > bo_t:
                                pos = 1; ent = c; sl = ext - slm * A
                                tp = (rh + rl) / 2 if p2 == 0 else (rh if p2 == 1 else ent + tpm * A)
                                bo = 0
                        if pos != 0 and (abs(tp - ent) < 0.02 * A or (pos == 1 and tp <= ent) or (pos == -1 and tp >= ent)):
                            pos = 0       # no room to target: skip
                    if pos != 0:
                        newpos = True     # entered at the close: manage from next bar
                else:
                    up = anchor + p1 * A; dn = anchor - p1 * A
                    if armS and h >= up:
                        pos = -1; ent = max(o, up); armS = False
                        tp = anchor if p2 == 1 else ent - tpm * A; sl = ent + slm * A
                    elif armL and lo <= dn:
                        pos = 1; ent = min(o, dn); armL = False
                        tp = anchor if p2 == 1 else ent + tpm * A; sl = ent - slm * A
                if pos != 0:
                    trades += 1
            # re-arm ORB sides once price is back inside the range
            if mode == 0 and pos == 0:
                if c < rh: armL = True
                if c > rl: armS = True
            # ---------------- manage ----------------
            if pos != 0 and not newpos:
                adv = (lo - ent) if pos == 1 else (ent - h)
                fav = (h - ent) if pos == 1 else (ent - lo)
                if real + adv - cost < worst: worst = real + adv - cost
                if dl > 0 and real + adv - cost <= -dl * A:
                    real = -dl * A; pos = 0; done = True
                elif adv <= -(abs(ent - sl)):
                    real += -abs(ent - sl) - cost; pos = 0
                elif fav >= abs(tp - ent) and (m > 0):
                    real += abs(tp - ent) - cost; pos = 0
                if real < worst: worst = real
                if dl > 0 and real <= -dl * A: done = True
                if dt > 0 and real >= dt * A: done = True
        if pos != 0 and lastc == lastc:
            real += (lastc - ent) * pos - cost
            if real < worst: worst = real
        if trades > 0:
            pnl[d] = real; mae[d] = min(worst, real); ntr[d] = trades
    return pnl, mae, ntr


@njit
def survive(pnl, mae, starts, ne, nf, dd, tgt, cap, mind):
    ns = len(starts); N = len(pnl)
    out = np.zeros((ns, 4))
    for i in range(ns):
        d = starts[i]; bal = 0.0; thr = -dd; best = 0.0; passed = 0; k = 0
        while d < N and k < 252:
            p = pnl[d]
            if p == p:
                a = mae[d] * ne; p = p * ne
                if bal + a <= thr or bal + p <= thr:
                    break
                bal += p
                if bal - dd > thr: thr = bal - dd
                if p > best: best = p
                if bal >= tgt and best <= 0.5 * bal:
                    passed = 1; d += 1; k += 1
                    break
            d += 1; k += 1
        out[i, 0] = passed; out[i, 1] = k
        if passed == 0:
            continue
        bal = 0.0; thr = -dd; qual = 0; paid = 0.0; alive = 0
        while d < N and alive < 252:
            p = pnl[d]
            if p == p:
                a = mae[d] * nf; p = p * nf
                if bal + a <= thr or bal + p <= thr:
                    break
                bal += p
                t2 = bal - dd
                if t2 > thr:
                    thr = t2 if t2 < 0.0 else 0.0
                if p >= mind: qual += 1
                if qual >= 5 and bal >= dd + 500.0:
                    w = min(cap, bal - dd)
                    bal -= w; paid += w * 0.9; qual = 0
            d += 1; alive += 1
        out[i, 2] = alive; out[i, 3] = paid
    return out


ACCTS = {"50K": (2000.0, 3000.0, 2000.0, 150.0), "150K": (4500.0, 9000.0, 5000.0, 250.0)}
WINDOWS = {  # name: (tz, range start, range end, [exits])
    "NY 9:30+5": ("America/New_York", 570, 575, [720, 955]),
    "NY 9:30+15": ("America/New_York", 570, 585, [720, 955]),
    "NY 9:30+30": ("America/New_York", 570, 600, [720, 955]),
    "LDN 7:30+30": ("Europe/London", 450, 480, [720, 1255]),
    "LDN 7:30+60": ("Europe/London", 450, 510, [720, 1255]),
}
ANCHORS = {"NY 9:30 open": ("America/New_York", 570, [720, 955]), "LDN 8:00 open": ("Europe/London", 480, [720, 1255])}


def variants():
    for w, (tz, rs, re_, exits) in WINDOWS.items():
        for ex in exits:
            for tpm in (0.1, 0.15, 0.25):
                for slm in (0.15, 0.25, 0.4):
                    for K in (1, 2, 3):
                        for dl in (0.0, 0.4):
                            for dt in (0.0, 0.2):
                                yield ("ORB scalp", w, tz, rs, re_, ex, 0, 0, tpm, slm, K, dl, dt)
            for p1 in (15, 60):
                for p2 in (0, 1, 2):
                    for slm in (0.03, 0.1, 0.2):
                        for K in (1, 2):
                            yield ("Failed-break fade", w, tz, rs, re_, ex, p1, p2, 0.15, slm, K, 0.0, 0.0)
    for w, (tz, rs, exits) in ANCHORS.items():
        for ex in exits:
            for p1 in (0.3, 0.5, 0.7):
                for p2, tpm in ((0, 0.15), (0, 0.3), (1, 0.0)):
                    for slm in (0.2, 0.35, 0.5):
                        yield ("Extension fade", w, tz, rs, rs + 1, ex, p1, p2, tpm, slm, 2, 0.0, 0.0)


def main():
    t0 = time.time()
    df = pd.read_parquet("nq_1m.parquet")
    mats = {}
    for tz in ("America/New_York", "Europe/London"):
        days, O, H, L, C = s.day_matrix(df, tz)
        wk = days.weekday < 5
        days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
        rng = np.nanmax(H, axis=1) - np.nanmin(L, axis=1)
        atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
        yrs = days.year.to_numpy()
        st = np.array([i for i in range(15, len(days) - 30, 5) if yrs[i] <= 2025])
        mats[tz] = (days, O, H, L, C, atr, yrs, st)
    rows = []
    for v in variants():
        fam, w, tz, rs, re_, ex, p1, p2, tpm, slm, K, dl, dt = v
        days, O, H, L, C, atr, yrs, st = mats[tz]
        p, a, n = family(O, H, L, C, atr, {"ORB scalp": 0, "Failed-break fade": 1, "Extension fade": 2}[fam],
                         rs, re_, ex, float(p1), p2, tpm, slm, K, dl, dt, COSTP)
        pu = p * PTV; au = a * PTV
        tr = ~np.isnan(pu)
        if tr.sum() < 300:
            continue
        v_ = pu[tr]; eq = np.cumsum(v_); mdd = (np.maximum.accumulate(eq) - eq).max()
        sy = yrs[st]
        base = {"family": fam, "window": w, "exit": f"{ex // 60:02d}:{ex % 60:02d}", "p1": p1, "p2": p2, "tp": tpm,
                "sl": slm, "K": K, "dayloss": dl, "daytp": dt, "days traded/yr": tr.sum() / 6.9,
                "win day %": (v_ > 0).mean() * 100, "1-MNQ total $": v_.sum(), "1-MNQ maxDD $": mdd,
                "worst day $": v_.min(), "IS $": pu[tr & (yrs <= 2023)].sum(), "OOS $": pu[tr & (yrs >= 2024) & (yrs <= 2025)].sum(),
                "2026 $": pu[tr & (yrs == 2026)].sum()}
        for acct, (dd, tgt, cap, mind) in ACCTS.items():
            for ne, nf in ((1, 1), (2, 1), (2, 2), (3, 1), (3, 2), (4, 2), (5, 2), (6, 3)):
                o = survive(pu, au, st, ne, nf, dd, tgt, cap, mind)
                ok = (o[:, 0] == 1) & (o[:, 2] >= 252)
                rows.append({**base, "acct": acct, "eval MNQ": ne, "funded MNQ": nf,
                             "IS surv %": ok[sy <= 2023].mean() * 100, "OOS surv %": ok[sy >= 2024].mean() * 100,
                             "pass %": (o[:, 0] == 1).mean() * 100,
                             "min yr surv %": min(ok[sy == y].mean() * 100 for y in range(2020, 2026)),
                             "payouts $ (survivors)": o[ok, 3].mean() if ok.any() else 0.0,
                             **{f"s{y}": ok[sy == y].mean() * 100 for y in range(2020, 2026)}})
    r = pd.DataFrame(rows)
    r.to_parquet("prop_strat.parquet")
    print(f"{len(r):,} variant x account x size combinations in {time.time() - t0:.0f}s")
    num = [c for c in r.columns if r[c].dtype.kind == "f" and c not in ("tp", "sl", "dayloss", "daytp", "p1")]
    show = r.copy(); show[num] = show[num].round(0)
    cols = ["family", "window", "exit", "p1", "p2", "tp", "sl", "K", "dayloss", "daytp", "acct", "eval MNQ", "funded MNQ",
            "IS surv %", "OOS surv %", "min yr surv %", "payouts $ (survivors)", "days traded/yr", "win day %",
            "1-MNQ total $", "1-MNQ maxDD $", "worst day $"]
    print("\nTop 25 by IS survival (2020-2023 starts), with OOS (2024-2025 starts):")
    print(show.sort_values("IS surv %", ascending=False).head(25)[cols].to_string(index=False))
    print("\nBest per family by IS survival:")
    print(show.sort_values("IS surv %", ascending=False).groupby("family").head(3)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
