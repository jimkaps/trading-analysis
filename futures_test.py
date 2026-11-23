"""Preset E, unchanged, on any 1-minute NQ dataset; optional comparison with a second dataset.

E: range 07:30-08:30 London, stop entry at range high/low (first fill only), stop = 1 x 14-day
average daily range, no take-profit, flat at 15:55 New York. 1 MNQ equivalent ($2/pt),
1 pt slippage round trip + $1.24 commission. D (fixed 1% stop) shown for reference.

Usage:
  python futures_test.py nq_fut_1m.parquet                    # E on futures, 2010-2026
  python futures_test.py nq_fut_1m.parquet nq_1m.parquet      # plus day-by-day comparison with the index data
"""
import sys

import numpy as np
import pandas as pd

import orb_sweep as s
from extra_test import gen_block

PTV, COST, COMM = 2.0, 1.0, 1.24
PERIODS = {"2014-19 (never seen)": range(2014, 2020), "2020-23": range(2020, 2024),
           "2024-25": range(2024, 2026), "2026": [2026]}


def daily_pnl(path, start=450, length=60, stop_mult=1.0, fixed_pct=None):
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.day_of_week < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    stop = np.full(len(days), np.nan) if fixed_pct else stop_mult * atr
    ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                           for d in days]).tz_convert("Europe/London")
    exm = (ny.hour * 60 + ny.minute).to_numpy()
    out = np.full(len(days), np.nan)
    for ex in np.unique(exm):
        p = gen_block(O, H, L, C, start, start + length, int(ex), 0.0, 0, stop, fixed_pct or 1.0, 0.0, 0, COST)
        out[exm == ex] = p[exm == ex]
    has_data = np.isfinite(H[:, start:start + length]).sum(axis=1) > 0
    return pd.Series(out * PTV - COMM, index=days).dropna(), pd.Series(has_data, index=days)


def summary(v):
    eq = v.cumsum(); yr = v.groupby(v.index.year).sum()
    return {"Total": round(v.sum()), "MaxDD": round((eq.cummax() - eq).max()), "Win%": round((v > 0).mean() * 100),
            "Trades": len(v), "$/trade": round(v.mean(), 1), "PosYrs": f"{(yr > 0).sum()}/{len(yr)}",
            **{p: round(sum(yr.get(y, 0) for y in ys)) for p, ys in PERIODS.items()}}


def main():
    fut = sys.argv[1]
    e, has = daily_pnl(fut)
    d, _ = daily_pnl(fut, fixed_pct=1.0)
    pd.set_option("display.width", 250)

    print("===== Preset E on", fut, "(1 MNQ equivalent, after costs) =====")
    print(pd.DataFrame({"E (1x ATR stop)": summary(e), "D (1% stop)": summary(d)}).to_string())

    yr = pd.DataFrame({"E": e.groupby(e.index.year).sum().round(0), "D": d.groupby(d.index.year).sum().round(0),
                       "E trades": e.groupby(e.index.year).size(),
                       "weekdays with data": has.groupby(has.index.year).sum()})
    yr["E $/trade"] = (yr.E / yr["E trades"]).round(1)
    print("\nBy year:\n" + yr.to_string())

    # robustness on the never-seen years: 18 nearby settings, as in market_test.py
    rows = []
    for st in (435, 450, 465):
        for ln in (45, 60, 90):
            for mult in (0.8, 1.0, 1.2, 1.5):
                v, _ = daily_pnl(fut, st, ln, mult)
                v = v[(v.index.year >= 2014) & (v.index.year < 2020)]
                rows.append({"stop": f"{mult}x ATR", "total": v.sum(),
                             "yrs>0": int((v.groupby(v.index.year).sum() > 0).sum())})
    r = pd.DataFrame(rows).groupby("stop")
    print("\n2014-19, 9 nearby range settings per stop (start 07:15-07:45, length 45-90 min):")
    print(pd.DataFrame({"mean total": r.total.mean().round(0), "% settings > 0": (r.total.apply(lambda x: (x > 0).mean()) * 100).round(0),
                        "mean years>0 of 6": r["yrs>0"].mean().round(1)}).to_string())

    if len(sys.argv) > 2:
        idx, _ = daily_pnl(sys.argv[2])
        both = pd.concat({"fut": e, "idx": idx}, axis=1)
        b = both.dropna()
        print(f"\n===== Futures vs {sys.argv[2]} on overlapping days =====")
        print(f"Days traded: futures {both.fut.notna().sum()}, index {both.idx.notna().sum()}, both {len(b)}")
        print(f"Same sign (both win or both lose): {(np.sign(b.fut) == np.sign(b.idx)).mean():.0%}; "
              f"daily correlation {b.fut.corr(b.idx):.2f}")
        cmp = pd.DataFrame({"futures": both.fut.groupby(both.index.year).sum(),
                            "index": both.idx.groupby(both.index.year).sum()}).round(0)
        cmp = cmp[cmp.index >= 2020]
        cmp.loc["Total"] = cmp.sum()
        print(cmp.to_string())


if __name__ == "__main__":
    main()
