"""Run presets D and E (and their neighbourhoods) on any index, with that market's micro-contract costs.

Usage: python market_test.py DATA.parquet POINT_VALUE COST_PTS_ROUND_TRIP LABEL
  NQ: python market_test.py nq_1m.parquet 2 1.0 MNQ
  ES: python market_test.py es_1m.parquet 5 0.5 MES
"""
import sys

import numpy as np
import pandas as pd

import orb_sweep as s
from extra_test import gen_block

pd.set_option("display.width", 250)
YRS = list(range(2020, 2027))
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}


def main():
    path, ptv, cost, label = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    comm = s.COMMISSION
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    years = days.year.to_numpy(); nd = len(days)
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    nan = np.full(nd, np.nan)

    def run(rs, ln, ex, sp, slp):
        p = gen_block(O, H, L, C, rs, rs + ln, ex, 0.0, 0, sp, slp, 0.0, 0, cost)
        return pd.Series(p * ptv - comm, index=days).dropna()

    # ---- exact presets ----
    out = {}
    for name, sp, slp in [("D (1% stop)", nan, 1.0), ("E (1x ATR stop)", atr, 1.0)]:
        v = run(450, 60, 1255, sp, slp)
        eq = v.cumsum(); yr = v.groupby(v.index.year).sum()
        out[name] = {**{str(y): round(yr.get(y, 0)) for y in YRS}, "Total": round(v.sum()),
                     "MaxDD": round((eq.cummax() - eq).max()), "Win%": round((v > 0).mean() * 100),
                     "Trades": len(v), "PosYrs": f"{(yr > 0).sum()}/{len(yr)}",
                     "Aug-Nov26": round(v[v.index >= "2026-08-03"].sum())}
    print(f"===== {label}: presets D and E (07:30-08:30 London, no TP, exit 20:55), 1 contract after costs =====")
    print(pd.DataFrame(out).to_string())

    # ---- neighbourhood: 18 settings x stop variants ----
    rows = []
    for rs in (435, 450, 465):
        for ln in (45, 60, 90):
            for ex in (1170, 1255):
                for name, sp, slp in [("fixed 0.75%", nan, 0.75), ("fixed 1% (D)", nan, 1.0),
                                      ("0.8x ATR", 0.8 * atr, 1.0), ("1x ATR (E)", atr, 1.0),
                                      ("1.2x ATR", 1.2 * atr, 1.0), ("1.5x ATR", 1.5 * atr, 1.0)]:
                    v = run(rs, ln, ex, sp, slp)
                    yr = v.groupby(v.index.year).sum()
                    eq = v.cumsum()
                    rec = {"stop": name, "setting": (rs, ln, ex), "total": v.sum(), "maxdd": (eq.cummax() - eq).max()}
                    for p, ys in PERIODS.items():
                        rec[p] = sum(yr.get(y, 0) for y in ys)
                    rec["posyrs"] = int((yr > 0).sum())
                    rows.append(rec)
    r = pd.DataFrame(rows)
    g = r.groupby("stop", sort=False)
    summ = pd.DataFrame({
        "mean total": g.total.mean().round(0),
        "mean maxDD": g.maxdd.mean().round(0),
        **{f"{p} mean": g[p].mean().round(0) for p in PERIODS},
        **{f"{p} %>0": (g[p].apply(lambda x: (x > 0).mean()) * 100).round(0) for p in PERIODS},
        "avg yrs>0": g.posyrs.mean().round(1),
    })
    print(f"\n===== {label}: 18 nearby settings (start 07:15-07:45, range 45-90 min, exit 19:30/20:55) =====")
    print(summ.to_string())
    print("\nE beats D on the same setting: " + ", ".join(
        f"{p} {((r[r.stop == '1x ATR (E)'][p].values - r[r.stop == 'fixed 1% (D)'][p].values) > 0).mean():.0%}"
        for p in PERIODS))


if __name__ == "__main__":
    main()
