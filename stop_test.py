"""Wider fixed stops vs ATR stops, with and without a break-even move, around preset D.
18 settings (start 07:15/07:30/07:45, range 45/60/90, exit 19:30/20:55), no take-profit,
compared with the current 1% stop.

Usage: python stop_test.py nq_1m.parquet
"""
import sys

import numpy as np
import pandas as pd

import orb_sweep as s
from ma_test import rec, summarise, STARTS, LENS, YRS
from extra_test import gen_block

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)
EXITS = [1170, 1255]


def main():
    df = pd.read_parquet(sys.argv[1])
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    years = days.year.to_numpy(); nd = len(days)
    day_rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr14 = pd.Series(day_rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    nan = np.full(nd, np.nan)
    ratio = atr14 / np.nanmean(C[:, 450:510], axis=1) * 100
    print(f"ATR14 as % of price: median {np.nanmedian(ratio):.2f}%, 10th-90th pct "
          f"{np.nanpercentile(ratio, 10):.2f}%-{np.nanpercentile(ratio, 90):.2f}%")
    variants = [(f"fixed {p}%", nan, p) for p in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0)] + \
               [("no stop (time exit only)", nan, 50.0)] + \
               [(f"{k} x ATR14", k * atr14, 1.0) for k in (0.6, 0.8, 1.0, 1.2, 1.5)]
    rows = []
    for rs in STARTS:
        for ln in LENS:
            for ex in EXITS:
                key = (rs, ln, ex, 99.0, 1.0)
                for be in (0.0, 1.0):
                    for name, sp, slp in variants:
                        p = gen_block(O, H, L, C, rs, rs + ln, ex, 0.0, 0, sp, slp, be, 0, s.COST_PTS)
                        v = p * s.PT_VALUE - s.COMMISSION
                        label = name + (" + BE at +1%" if be else "")
                        rows.append(rec(key, "(none)" if label == "fixed 1.0%" else label, v, ~np.isnan(v), years))
        print(f"start {rs // 60:02d}:{rs % 60:02d} done", flush=True)
    r = summarise(rows)
    d = r[r.setting == (450, 60, 1255, 99.0, 1.0)].sort_values("ret_dd", ascending=False)
    print("\nPreset D (07:30-08:30, exit 20:55):")
    print(d[["test", "trades", "maxdd", "total", "ret_dd"] + YRS].round(1).to_string(index=False))
    r.to_pickle("stop_rows.pkl")


if __name__ == "__main__":
    main()
