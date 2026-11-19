"""Will NQ preset E + gold preset E survive a funded (prop) account?

Builds day-by-day paths (closed P&L and worst open loss) for 1 MNQ of NQ-E and 1 MGC of gold-E, then combines
n MNQ + m MGC. Worst open losses are ADDED (both markets assumed to hit their worst at the same moment).

Two tests, starts every 5 trading days 2020-2025:
  1. Single account (single_acct.sim): pass one evaluation (EOD trailing DD, target, best day <= 50%),
     then keep the funded account alive 252 trading days, taking payouts.
  2. One-year campaign (prop_sim.campaign): rebuy evaluations after any failure; net = payouts - fees.

Usage: python combo_funded.py
"""
import numpy as np
import pandas as pd

import orb_sweep as s
from prop_paths import path_block
from single_acct import sim
from prop_sim import campaign

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)

ACCTS = {"50K": (2000.0, 3000.0, 2000.0, 150.0, 150.0), "150K": (4500.0, 9000.0, 5000.0, 250.0, 150.0)}
# name: dd, target, payout cap, min qualifying day, eval fee/month


def paths(path, ptv, cost, comm):
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    p, a, f = path_block(O, H, L, C, 450, 510, 1255, atr, 1.0, cost)
    return pd.DataFrame({"pnl": p * ptv - comm, "mae": a * ptv - comm, "mfe": f * ptv}, index=days)


def main():
    nq = paths("nq_1m.parquet", 2.0, 1.0, 1.24)
    au = paths("gold_1m.parquet", 10.0, 0.2, 1.24)
    j = nq.join(au, how="outer", lsuffix="_nq", rsuffix="_au")
    print(f"Per contract: NQ-E worst open loss ${j.mae_nq.min():,.0f}, median losing day ${j.pnl_nq[j.pnl_nq < 0].median():,.0f}; "
          f"gold-E worst open loss ${j.mae_au.min():,.0f}, median losing day ${j.pnl_au[j.pnl_au < 0].median():,.0f}")
    print(f"Daily P&L correlation: {j.pnl_nq.corr(j.pnl_au):.2f}")
    years = j.index.year.to_numpy()
    N = len(j)
    starts = np.array([i for i in range(15, N - 30, 5) if years[i] <= 2025])
    st_year = years[starts]

    rows = []
    for acct, (dd, tgt, cap, mind, fee) in ACCTS.items():
        for n in range(0, 6):
            for m in range(0, 4):
                if n == 0 and m == 0:
                    continue
                pn = np.nan_to_num(j.pnl_nq.to_numpy()) * n + np.nan_to_num(j.pnl_au.to_numpy()) * m
                an = np.nan_to_num(j.mae_nq.to_numpy()) * n + np.nan_to_num(j.mae_au.to_numpy()) * m
                fn = np.nan_to_num(j.mfe_nq.to_numpy()) * n + np.nan_to_num(j.mfe_au.to_numpy()) * m
                traded = ~(j.pnl_nq.isna().to_numpy() & j.pnl_au.isna().to_numpy())
                pn = np.where(traded, pn, np.nan); an = np.where(traded, an, np.nan)
                out = sim(pn, an, starts, 1, dd, tgt, cap, mind)
                passed = out[:, 0] == 1
                alive = passed & (out[:, 2] >= 252)
                camp = np.array([campaign(pn, an, fn, s0, 252, 1, dd, tgt, cap, 0, 0.5, 0, 1.0, 0.9, fee, 100)
                                 for s0 in starts if s0 + 252 <= N])
                net = camp[:, 0]
                by_year = {y: alive[st_year == y].mean() * 100 for y in range(2020, 2026)}
                rows.append({"acct": acct, "MNQ": n, "MGC": m,
                             "pass %": passed.mean() * 100,
                             "survive 1yr %": alive.mean() * 100,
                             "survive 6m %": (passed & (out[:, 2] >= 126)).mean() * 100,
                             "median funded days": np.median(out[passed, 2]) if passed.any() else 0,
                             "payouts/acct $": out[:, 3].mean(),
                             "campaign median $/yr": np.median(net),
                             "campaign % yrs >0": (net > 0).mean() * 100,
                             "campaign worst $": net.min(),
                             "evals/yr": camp[:, 3].mean(),
                             **{f"surv {y}": v for y, v in by_year.items()}})
    r = pd.DataFrame(rows)
    r.to_csv("combo_funded_results.csv", index=False)
    cols = ["acct", "MNQ", "MGC", "pass %", "survive 6m %", "survive 1yr %", "median funded days", "payouts/acct $",
            "campaign median $/yr", "campaign % yrs >0", "campaign worst $", "evals/yr"]
    for acct in ACCTS:
        q = r[r.acct == acct]
        print(f"\n===== {acct} account (EOD trailing drawdown ${ACCTS[acct][0]:,.0f}) =====")
        print(q[cols].round(0).to_string(index=False))
    print("\nOne-year survival % by start year (best few):")
    top = r.sort_values("survive 1yr %", ascending=False).head(8)
    print(top[["acct", "MNQ", "MGC", "survive 1yr %"] + [f"surv {y}" for y in range(2020, 2026)]].round(0).to_string(index=False))


if __name__ == "__main__":
    main()
