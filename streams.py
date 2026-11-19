"""Daily P&L streams (per 1 micro contract, after costs) for combining strategies.
Output: streams.parquet with <name>_pnl and <name>_mae columns, indexed by London date (weekdays).
"""
import numpy as np
import pandas as pd

import orb_sweep as s
from prop_search import block

# name: (file, tz, start, len, exit, tp x ATR (99 = none), sl x ATR, $/pt, slippage pts round trip)
STREAMS = {
    "NQ_E":       ("nq_1m.parquet", "Europe/London", 450, 60, 1255, 99.0, 1.0, 2.0, 1.0),
    "NQ_E_tp07":  ("nq_1m.parquet", "Europe/London", 450, 60, 1255, 0.7, 1.0, 2.0, 1.0),
    "NQ_E_tp05":  ("nq_1m.parquet", "Europe/London", 450, 60, 1255, 0.5, 1.0, 2.0, 1.0),
    "NQ_NY":      ("nq_1m.parquet", "America/New_York", 600, 30, 955, 0.5, 0.2, 2.0, 1.0),
    "GC_E":       ("gold_1m.parquet", "Europe/London", 450, 60, 1255, 99.0, 1.0, 10.0, 0.2),
    "GC_E_tp07":  ("gold_1m.parquet", "Europe/London", 450, 60, 1255, 0.7, 1.0, 10.0, 0.2),
    "ES_E":       ("es_1m.parquet", "Europe/London", 450, 60, 1255, 99.0, 1.0, 5.0, 0.5),
}


def main():
    cache = {}
    out = {}
    for name, (f, tz, rs, ln, ex, tp, sl, ptv, cost) in STREAMS.items():
        if (f, tz) not in cache:
            df = pd.read_parquet(f)
            days, O, H, L, C = s.day_matrix(df, tz)
            wk = days.weekday < 5
            days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
            rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
            atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
            cache[(f, tz)] = (days, O, H, L, C, atr)
        days, O, H, L, C, atr = cache[(f, tz)]
        p, m = block(O, H, L, C, rs, rs + ln, np.array([ex]), atr, np.array([tp]), np.array([sl]), cost)
        out[f"{name}_pnl"] = pd.Series(p[:, 0, 0, 0].astype(float) * ptv - 1.24, index=days)
        out[f"{name}_mae"] = pd.Series(m[:, 0, 0, 0].astype(float) * ptv - 1.24, index=days)
    st = pd.DataFrame(out)
    st.to_parquet("streams.parquet")
    pnl = st[[c for c in st if c.endswith("_pnl")]].fillna(0)
    pnl.columns = [c[:-4] for c in pnl.columns]
    yr = pnl.groupby(pnl.index.year).sum().round(0)
    print("Yearly P&L per 1 micro contract:")
    print(yr.to_string())
    eq = pnl.cumsum()
    print("\nTotal:", pnl.sum().round(0).to_dict())
    print("Max drawdown:", (eq.cummax() - eq).max().round(0).to_dict())
    print("Daily Sharpe:", (pnl.mean() / pnl.std() * np.sqrt(252)).round(2).to_dict())
    print("Win rate:", ((pnl > 0).sum() / (pnl != 0).sum()).round(2).to_dict())
    print("\nCorrelation of daily P&L:")
    print(pnl.corr().round(2).to_string())


if __name__ == "__main__":
    main()
