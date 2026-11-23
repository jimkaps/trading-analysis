"""Slippage sensitivity for preset E (07:30-08:30 London, 1 x ATR14 stop, no TP, flat 15:55 New York).

Baseline cost model used everywhere else: 1 pt round trip (= 2 ticks per side on NQ/MNQ) + $1.24 commission,
stop entries fill at the range level (or the bar open if it opens beyond), stop-outs fill exactly at the stop.

Tests:
  1. Fixed slippage: 0 to 6 pts round trip.
  2. Gap-through stop-outs: if the minute opens beyond the stop, fill at that open instead of the stop.
  3. Fast-market slippage: entry and stop-out slip by k x the high-low range of their fill minute
     (breakout and stop minutes are the fastest of the day), k = 0.1, 0.25, 0.5. Plus gap-through.

Usage: python slippage_test.py [nq_1m_2012_2026.parquet]
"""
import sys

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s

PTV, COMM = 2.0, 1.24


@njit
def trades(O, H, L, C, rs, re_, exm, stop_pts):
    """Per day: gross pts, entry-minute range, stopped flag, extra pts lost if stop fill at gapped open,
    stop-minute range. nan = no trade."""
    nd = O.shape[0]
    out = np.full((nd, 5), np.nan)
    for d in range(nd):
        ex = exm[d]
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
        sp = stop_pts[d]
        if sp != sp:
            continue
        side = 0; ent = -1; px = 0.0
        for m in range(re_, ex):
            h = H[d, m]
            if h != h:
                continue
            o = O[d, m]; a = h >= rh; b = L[d, m] <= rl
            if a or b:
                if o >= rh: side = 1; px = o
                elif o <= rl: side = -1; px = o
                elif a and b:
                    if rh - o <= o - rl: side = 1; px = rh
                    else: side = -1; px = rl
                elif a: side = 1; px = rh
                else: side = -1; px = rl
                ent = m
                break
        if ent < 0:
            continue
        stop = px - sp if side == 1 else px + sp
        erng = H[d, ent] - L[d, ent]
        res = np.nan; stopped = 0.0; gap = 0.0; srng = 0.0; lastc = px
        for m in range(ent, ex):
            h = H[d, m]
            if h != h:
                continue
            lo = L[d, m]; lastc = C[d, m]
            if side == 1 and lo <= stop:
                res = stop - px; stopped = 1.0; srng = h - lo
                if m > ent and O[d, m] < stop: gap = stop - O[d, m]
                break
            if side == -1 and h >= stop:
                res = px - stop; stopped = 1.0; srng = h - lo
                if m > ent and O[d, m] > stop: gap = O[d, m] - stop
                break
        if res != res:
            res = (lastc - px) * side
        out[d, 0] = res; out[d, 1] = erng; out[d, 2] = stopped; out[d, 3] = gap; out[d, 4] = srng
    return out


def load(path):
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.day_of_week < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                           for d in days]).tz_convert("Europe/London")
    exm = (ny.hour * 60 + ny.minute).to_numpy().astype(np.int64)
    t = trades(O, H, L, C, 450, 510, exm, atr)
    return pd.DataFrame(t, index=days, columns=["gross", "erng", "stopped", "gap", "srng"]).dropna()


def stats(usd, label):
    eq = usd.cumsum(); yr = usd.groupby(usd.index.year).sum()
    return {"scenario": label, "total": round(usd.sum()), "$/trade": round(usd.mean(), 1),
            "maxDD": round((eq.cummax() - eq).max()), "pos yrs": f"{(yr > 0).sum()}/{len(yr)}"}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    t = load(path)
    pd.set_option("display.width", 250)
    for lab, a, b in [("2020-2026 (where E was built)", 2020, 2026), ("2014-2019 (never seen)", 2014, 2019)]:
        x = t[(t.index.year >= a) & (t.index.year <= b)]
        rows = []
        for rt in (0, 0.5, 1, 2, 3, 4, 6):
            rows.append(stats((x.gross - rt) * PTV - COMM, f"fixed {rt:g} pt RT" + ("  <- baseline" if rt == 1 else "")))
        rows.append(stats((x.gross - 1 - x.gap) * PTV - COMM, "baseline + gap-through stops"))
        for k in (0.1, 0.25, 0.5):
            slip = k * x.erng + k * x.srng * x.stopped
            rows.append(stats((x.gross - 1 - x.gap - slip) * PTV - COMM, f"baseline + gaps + {k:g}x fill-minute range"))
        print(f"\n===== Preset E, 1 MNQ, {lab}: {len(x)} trades =====")
        print(pd.DataFrame(rows).set_index("scenario").to_string())
        # break-even slippage
        be = x.gross.mean() - COMM / PTV
        print(f"Break-even round-trip slippage: {be:.1f} pts ({be * 2:.0f} ticks per side). "
              f"Median entry-minute range {x.erng.median():.1f} pts; stop-outs {x.stopped.mean():.0%} of trades, "
              f"gapped through on {(x.gap > 0).sum()} of them (avg {x.gap[x.gap > 0].mean():.1f} pts)")


if __name__ == "__main__":
    main()
