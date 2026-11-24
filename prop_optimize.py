"""Prop-firm management rules for preset E on Lucid Flex 50K (rules read 23 Nov 2026).

Preset E's entry and exit are unchanged. What varies is how the trade is managed inside the account:
  ne      : MNQ in the evaluation
  cap     : evaluation daily profit cap in $ (take profit when the day's open profit reaches it; 0 = none).
            Lucid Flex needs best day <= 40% of profit, so a $1,200 cap on a $3,000 target can't break it.
  coast   : once eval profit >= coast x target, trade 1 MNQ (0 = off)
  nf_pre  : MNQ in the funded account before the trailing floor locks (+$2,100 peak -> floor +$100)
  nf_post : MNQ in the funded account after it locks
  room    : size so that n x full stop <= room x (balance - floor), minimum 1 MNQ (0 = off)

Lucid Flex 50K: $88.20 per evaluation/reset (coupon price), $3,000 target, $2,000 EOD trailing drawdown
locking at +$100, 40% eval consistency, 3-day minimum; funded: payout once 5 days >= $150 and cycle profit
> 0, max 50% of profit and $2,000, min $500, 90% split, 5 payouts then live (account retired here).
Drawdowns are checked against the worst open loss each day.

Periods: 2020-26 as is; 2014-19 with prices scaled x4.5 so dollar risk matches today (E had no edge then).

Usage: python prop_optimize.py [nq_1m_2012_2026.parquet]
"""
import itertools
import sys

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s
from prop_firms import paths

PTV, COST, COMM = 2.0, 1.0, 1.24
FEE, TARGET, DD, ECONS, EDAYS = 88.2, 3000.0, 2000.0, 0.4, 3
QTHR, QDAYS, PCT, CAP, MINPAY, SPLIT, MAXPAY = 150.0, 5, 0.5, 2000.0, 500.0, 0.9, 5


@njit
def day_result(fin, rmax, pmin, L, n, cap, cpc):
    """$ result and worst open $ for n contracts with an optional daily take-profit cap."""
    if cap > 0:
        P = (cap / n + cpc) / PTV                      # favourable pts needed to bank `cap` after costs
        t = np.searchsorted(rmax[:L], P)
        stopped_last = fin <= pmin[L - 1] + 1e-9          # final result = worst point -> stopped out
        if t < L and not (t == L - 1 and stopped_last):     # cap and stop in the same minute counts as the stop
            return cap, (pmin[t] * PTV - cpc) * n
    return (fin * PTV - cpc) * n, (pmin[L - 1] * PTV - cpc) * n if L > 0 else 0.0


@njit
def simulate(fin, rmax, pmin, nlen, stop_usd, start, ne, cap, coast, nf_pre, nf_post, room):
    cpc = COST * PTV + COMM
    nd = fin.shape[0]
    cum = -FEE; bought = 1; passed = 0; pays = 0
    curve = np.zeros(nd)
    phase = 0; bal = 0.0; peak = 0.0; floor = -DD; locked = False; best = 0.0; days = 0
    npay = 0; base = 0.0; qual = 0
    for d in range(start, nd):
        g = fin[d]
        if g == g:
            L = nlen[d]
            if phase == 0:
                n = 1 if (coast > 0 and bal >= coast * TARGET) else ne
                c = cap
            else:
                n = nf_post if locked else nf_pre
                c = 0.0
            if room > 0:
                while n > 1 and n * stop_usd[d] > room * (bal - floor):
                    n -= 1
            day, worst = day_result(g, rmax[d], pmin[d], L, n, c, cpc)
            if bal + worst <= floor or bal + day <= floor:
                cum -= FEE; bought += 1
                phase = 0; bal = 0.0; peak = 0.0; floor = -DD; locked = False; best = 0.0; days = 0
                npay = 0; base = 0.0; qual = 0
                curve[d] = cum
                continue
            bal += day; days += 1
            if bal > peak:
                peak = bal
                if not locked:
                    floor = min(peak - DD, 100.0)
                    if floor >= 100.0:
                        locked = True
            if phase == 0:
                if day > best: best = day
                if bal >= TARGET and days >= EDAYS and best <= ECONS * bal:
                    passed += 1
                    phase = 1; bal = 0.0; peak = 0.0; floor = -DD; locked = False; npay = 0; base = 0.0; qual = 0
            else:
                if day >= QTHR: qual += 1
                if qual >= QDAYS and bal - base > 0:
                    amt = min(CAP, PCT * bal)
                    if amt >= MINPAY:
                        bal -= amt; cum += amt * SPLIT; pays += 1; npay += 1; qual = 0; base = bal
                        if npay >= MAXPAY:
                            cum -= FEE; bought += 1
                            phase = 0; bal = 0.0; peak = 0.0; floor = -DD; locked = False; best = 0.0; days = 0
                            npay = 0; base = 0.0; qual = 0
        curve[d] = cum
    return curve, bought, passed, pays


def build(path):
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.day_of_week < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                           for d in days]).tz_convert("Europe/London")
    exm = (ny.hour * 60 + ny.minute).to_numpy().astype(np.int64)
    nocut = np.full(len(days), -1, dtype=np.int64)
    fin, adv, fav, nlen = paths(O, H, L, C, 450, 510, exm, nocut, nocut, atr)
    rmax = np.maximum.accumulate(fav.astype(np.float64), axis=1)
    pmin = np.minimum.accumulate(adv.astype(np.float64), axis=1)
    return days, fin, rmax, pmin, nlen, atr


def period(days, fin, rmax, pmin, nlen, atr, a, b, scale):
    sel = (days.year >= a) & (days.year <= b)
    i0 = int(np.argmax(sel)); i1 = int(len(sel) - np.argmax(sel[::-1]))
    sl = slice(i0, i1)
    stop_usd = np.nan_to_num(atr[sl] * scale * PTV + COST * PTV + COMM, nan=1e9)
    return (fin[sl] * scale, rmax[sl] * scale, pmin[sl] * scale, nlen[sl], stop_usd), (i1 - i0)


def score(args, nd, rule, step=42):
    finals = []
    for st in range(15, nd - 252, step):
        c = simulate(*args, st, *rule)[0]
        finals.append(c[-1] / ((nd - st) / 252))
    full = simulate(*args, 15, *rule)
    return np.array(finals), full


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    days, fin, rmax, pmin, nlen, atr = build(path)
    new, nnew = period(days, fin, rmax, pmin, nlen, atr, 2020, 2026, 1.0)
    old, nold = period(days, fin, rmax, pmin, nlen, atr, 2014, 2019, 4.5)

    # zero-edge control: same days, trade direction flipped at random (path mirrored), averaged over 5 draws
    if "--control" in sys.argv:
        rules = {"current plan 2/1": (2, 0.0, 0.0, 1, 1, 0.0), "2/2": (2, 0.0, 0.0, 2, 2, 0.0),
                 "2/2 + $1,200 cap": (2, 1200.0, 0.0, 2, 2, 0.0), "3/1 + $1,200 cap": (3, 1200.0, 0.0, 2, 1, 0.0),
                 "2/1 + $1,200 cap": (2, 1200.0, 0.0, 1, 1, 0.0), "2/2 + $900 cap": (2, 900.0, 0.0, 2, 2, 0.0)}
        f, rm, pm, nl, su = new
        out = {k: [] for k in rules}
        for seed in range(5):
            g = np.random.default_rng(seed).random(len(f)) < 0.5
            # mirrored day: best open profit so far = -(worst point so far), worst = -(best so far)
            rmx = np.where(g[:, None], -pm, rm); pmn = np.where(g[:, None], -rm, pm)
            ff = np.where(g, -f, f)
            for k, rule in rules.items():
                out[k].append(np.median(score((ff, rmx, pmn, nl, su), nnew, rule)[0]))
        print("===== Zero-edge control, 2020-26 days with random direction (median $/yr over 5 draws) =====")
        for k, v in out.items():
            print(f"{k:22s} {np.mean(v):8.0f}   (draws {', '.join(f'{x:.0f}' for x in v)})")
        return

    grid = list(itertools.product([1, 2, 3], [0.0, 900.0, 1200.0], [0.0, 0.7], [1, 2], [1, 2, 3], [0.0, 0.6]))
    rows = []
    for ne, cap, coast, nfp, nfq, room in grid:
        rule = (ne, cap, coast, nfp, nfq, room)
        fn, (cn, b, p, k) = score(new, nnew, rule)
        fo, (co, *_) = score(old, nold, rule)
        rows.append({"eval MNQ": ne, "eval day cap": int(cap), "coast": coast, "funded pre-lock": nfp,
                     "funded post-lock": nfq, "room": room,
                     "20-26 median/yr": np.median(fn), "20-26 worst start": fn.min(),
                     "20-26 net": cn[-1], "evals": b, "passed": p, "payouts": k,
                     "14-19 median/yr": np.median(fo), "14-19 worst start": fo.min()})
    r = pd.DataFrame(rows)
    r.to_csv("prop_optimize_results.csv", index=False)
    base = r[(r["eval MNQ"] == 2) & (r["eval day cap"] == 0) & (r.coast == 0) & (r["funded pre-lock"] == 1)
             & (r["funded post-lock"] == 1) & (r.room == 0)].iloc[0]
    print("===== Baseline: current plan (2 MNQ eval, 1 MNQ funded, no extra rules) =====")
    print(base.round(0).to_string())

    # effect of each lever, averaged over everything else
    print("\n===== Each lever, median over all other settings ($/yr) =====")
    for col in ["eval MNQ", "eval day cap", "coast", "funded pre-lock", "funded post-lock", "room"]:
        g = r.groupby(col)[["20-26 median/yr", "20-26 worst start", "14-19 median/yr"]].median().round(0)
        print(f"-- {col} --"); print(g.to_string())

    # best rules: rank on 2020-26 worst start, require 2014-19 no worse than baseline - $150/yr
    ok = r[r["14-19 median/yr"] >= base["14-19 median/yr"] - 150]
    print("\n===== Top 15 by 2020-26 worst start date (2014-19 loss no more than $150/yr worse than baseline) =====")
    print(ok.sort_values("20-26 worst start", ascending=False).head(15).round(0).to_string(index=False))
    print("\n===== Top 10 by 2020-26 median, any 2014-19 =====")
    print(r.sort_values("20-26 median/yr", ascending=False).head(10).round(0).to_string(index=False))


if __name__ == "__main__":
    main()
