"""Monte Carlo for preset E on 1 MNQ (baseline costs: 1 pt round trip + $1.24).

Resamples E's actual daily results in blocks of ~20 trading days (stationary block bootstrap), so
losing streaks and volatile spells stay together. Each day's P&L is sampled with that day's stop size.

Edge scenarios (what the future might look like):
  2020-26 as is   : resample 2020-2026 trades
  half edge       : same, with the average trade cut in half
  2014-19 as is   : resample 2014-2019 trades (the period where E had no edge), rescaled to 2020-26
                    point sizes so the dollar swings are comparable
  zero edge       : 2020-26 trades with the average shifted to exactly -$0 before costs (costs still paid)

Outputs: confidence interval for the average trade; 1-year and 3-year distributions of P&L, max
drawdown, longest stretch without a new high, longest run of losing trades; and the starting balance needed
so the account isn't busted (equity below the day's full stop + $100 margin; the stop caps any one loss).

Usage: python monte_carlo.py [nq_1m_2012_2026.parquet]
"""
import sys

import numpy as np
import pandas as pd
from numba import njit

from slippage_test import load, PTV, COMM

N_PATHS, BLOCK, YEAR = 10000, 20, 252
MARGIN = 100.0


@njit
def _seed(x):
    np.random.seed(x)


@njit
def block_index(n_src, length, n_paths):
    """Stationary bootstrap indices: blocks with geometric lengths (mean BLOCK)."""
    idx = np.empty((n_paths, length), dtype=np.int64)
    p = 1.0 / BLOCK
    for i in range(n_paths):
        j = np.random.randint(n_src)
        idx[i, 0] = j
        for t in range(1, length):
            if np.random.random() < p:
                j = np.random.randint(n_src)
            else:
                j = (j + 1) % n_src
            idx[i, t] = j
    return idx


@njit
def path_stats(P, S, start_cash):
    n, T = P.shape
    out = np.empty((n, 6))
    for i in range(n):
        eq = 0.0; peak = 0.0; dd = 0.0; uw = 0; uwmax = 0; streak = 0.0; worst = 0.0
        cash = start_cash; bust = 0.0
        for t in range(T):
            p = P[i, t]
            if bust == 0.0:
                if cash < S[i, t] + MARGIN:
                    bust = 1.0
                else:
                    cash += p
            eq += p
            if eq > peak:
                peak = eq; uw = 0
            else:
                uw += 1
                if uw > uwmax: uwmax = uw
            if peak - eq > dd: dd = peak - eq
            streak = streak + 1.0 if p < 0 else 0.0
            if streak > worst: worst = streak
        out[i, 0] = eq; out[i, 1] = dd; out[i, 2] = uwmax; out[i, 3] = worst; out[i, 4] = bust; out[i, 5] = cash
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    t = load(path)
    _seed(7)
    t["usd"] = (t.gross - 1.0) * PTV - COMM
    new = t[(t.index.year >= 2020)].copy()
    old = t[(t.index.year >= 2014) & (t.index.year < 2020)].copy()

    # full stop in $ on 1 MNQ for each day (1 x ATR14, as preset E uses)
    stop_new = stop_usd(path, new.index); stop_old = stop_usd(path, old.index)
    scale = np.median(stop_new) / np.median(stop_old)      # 2014-19 point sizes -> 2020-26 point sizes

    scen = {
        "2020-26 as is": (new.usd.to_numpy(), stop_new),
        "half edge": (new.usd.to_numpy() - new.usd.mean() / 2, stop_new),
        "2014-19 as is (rescaled)": ((old.gross.to_numpy() * scale - 1.0) * PTV - COMM, stop_old * scale),
        "zero edge": (new.usd.to_numpy() - (new.gross.mean() * PTV), stop_new),
    }

    pd.set_option("display.width", 250)
    # 1. confidence interval for the average trade (block bootstrap of the mean)
    print("===== Average trade, 1 MNQ after costs: block-bootstrap 90% interval =====")
    for lab, x in [("2020-26", new.usd.to_numpy()), ("2014-19", old.usd.to_numpy()),
                   ("2014-26", np.r_[old.usd.to_numpy(), new.usd.to_numpy()])]:
        idx = block_index(len(x), len(x), 2000)
        m = x[idx].mean(axis=1)
        print(f"{lab}: mean ${x.mean():.1f}  90% interval ${np.percentile(m, 5):.1f} to ${np.percentile(m, 95):.1f}  "
              f"P(mean <= 0) {np.mean(m <= 0):.1%}")

    # 2. path distributions
    for horizon, T in [("1 year", YEAR), ("3 years", 3 * YEAR)]:
        rows = []
        for lab, (P, S) in scen.items():
            idx = block_index(len(P), T, N_PATHS)
            r = path_stats(P[idx], S[idx], 1e12)
            pnl, dd, uw, ls = r[:, 0], r[:, 1], r[:, 2], r[:, 3]
            rows.append({"scenario": lab, "median P&L": round(np.median(pnl)), "5th pct P&L": round(np.percentile(pnl, 5)),
                         "P(loss)": f"{np.mean(pnl < 0):.0%}", "median maxDD": round(np.median(dd)),
                         "95th pct maxDD": round(np.percentile(dd, 95)), "median days w/o new high": int(np.median(uw)),
                         "95th pct days w/o high": int(np.percentile(uw, 95)), "95th pct losing trades in a row": int(np.percentile(ls, 95))})
        print(f"\n===== {horizon} ({T} trading days), {N_PATHS:,} paths =====")
        print(pd.DataFrame(rows).set_index("scenario").to_string())

    # 3. starting balance vs chance of being busted
    print("\n===== Chance of being busted (can't cover the day's full stop + $100), 1 MNQ =====")
    rows = []
    for lab, (P, S) in scen.items():
        rec = {"scenario": lab}
        for T, tag in [(YEAR, "1y"), (3 * YEAR, "3y")]:
            idx = block_index(len(P), T, N_PATHS)
            PP, SS = P[idx], S[idx]
            for cash in (2000, 5000, 8000, 10000, 15000, 20000):
                rec[f"${cash // 1000}k {tag}"] = f"{path_stats(PP, SS, float(cash))[:, 4].mean():.0%}"
        rows.append(rec)
    print(pd.DataFrame(rows).set_index("scenario").to_string())
    print(f"\nMedian full stop on 1 MNQ: 2020-26 ${np.median(stop_new):,.0f}, 2014-19 ${np.median(stop_old):,.0f} "
          f"(2014-19 rescaled by {scale:.2f}x)")


def stop_usd(path, index):
    import orb_sweep as s
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.day_of_week < 5
    days, H, L = days[wk], H[wk], L[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng, index=days).rolling(14, min_periods=10).mean().shift(1)
    return (atr.reindex(index).to_numpy() * PTV + COMM)


if __name__ == "__main__":
    main()
