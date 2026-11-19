"""Search for an NQ ORB version that passes ONE evaluation and keeps the funded account alive for a year.

Levers searched:
  stop      : k x 14-day average daily range, k in 0.6 / 0.8 / 1.0 / 1.2 (preset E = 1.0)
  skip      : no trade on days when that stop would cost more than $X per MNQ (high-volatility days)
  account   : trailing drawdown / profit target, from 50K-class up to 300K-class accounts
  size      : MNQ during the evaluation and MNQ once funded (separately)
Rules: EOD trailing drawdown checked against open loss (locks at the starting balance once funded profit
exceeds it), best day <= 50% of profit to pass, eval must pass within 252 trading days. Funded: payout after
5 days >= $250 and balance >= DD + $500, withdraw down to DD above start (capped), 90% split.
Success = passed AND funded account alive for 252 trading days. Starts every 5 trading days, 2020-2025.

Usage: python survive_search.py
"""
import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s
from prop_paths import path_block

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)

ACCTS = {  # label: (trailing DD, target, payout cap)
    "50K  ($2.0k DD)": (2000.0, 3000.0, 2000.0),
    "100K ($3.0k DD)": (3000.0, 6000.0, 3000.0),
    "150K ($4.5k DD)": (4500.0, 9000.0, 5000.0),
    "250K ($6.5k DD)": (6500.0, 15000.0, 6000.0),
    "300K ($7.5k DD)": (7500.0, 20000.0, 7000.0),
}
MULTS = [0.6, 0.8, 1.0, 1.2]
SKIPS = [np.inf, 1200.0, 1000.0, 800.0, 600.0]


@njit
def run(pnl, mae, starts, ne, nf, dd, tgt, cap):
    ns = len(starts); N = len(pnl)
    out = np.zeros((ns, 4))   # passed, eval days, funded days alive, payouts
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
                if p >= 250.0: qual += 1
                if qual >= 5 and bal >= dd + 500.0:
                    w = min(cap, bal - dd)
                    bal -= w; paid += w * 0.9; qual = 0
            d += 1; alive += 1
        out[i, 2] = alive; out[i, 3] = paid
    return out


def main():
    df = pd.read_parquet("nq_1m.parquet")
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    years = days.year.to_numpy()
    starts = np.array([i for i in range(15, len(days) - 30, 5) if years[i] <= 2025])
    sy = years[starts]
    rows = []
    for k in MULTS:
        p, a, f = path_block(O, H, L, C, 450, 510, 1255, k * atr, 1.0, 1.0)
        pnl0 = p * 2.0 - 1.24; mae0 = a * 2.0 - 1.24
        stop_usd = k * atr * 2.0
        for skip in SKIPS:
            keep = ~(stop_usd > skip)
            pnl = np.where(keep, pnl0, np.nan); mae = np.where(keep, mae0, np.nan)
            v = pnl[~np.isnan(pnl)]
            eq = np.cumsum(v); mdd = (np.maximum.accumulate(eq) - eq).max()
            for acct, (dd, tgt, cap) in ACCTS.items():
                for ne in range(1, 7):
                    for nf in range(1, ne + 1):
                        o = run(pnl, mae, starts, ne, nf, dd, tgt, cap)
                        passed = o[:, 0] == 1; ok = passed & (o[:, 2] >= 252)
                        by = [ok[sy == y].mean() * 100 for y in range(2020, 2026)]
                        rows.append({"stop xATR": k, "skip if stop >$": skip, "account": acct, "eval MNQ": ne,
                                     "funded MNQ": nf, "pass %": passed.mean() * 100, "survive 1yr %": ok.mean() * 100,
                                     "worst start-yr %": min(by), "best start-yr %": max(by),
                                     "median eval days": np.median(o[passed, 1]) if passed.any() else np.nan,
                                     "payouts in yr $": o[ok, 3].mean() if ok.any() else 0.0,
                                     "trades/yr": len(v) / 6.9, "1-MNQ total $": v.sum(), "1-MNQ maxDD $": mdd,
                                     **{f"s{y}": b for y, b in zip(range(2020, 2026), by)}})
        print(f"stop {k}x done", flush=True)
    r = pd.DataFrame(rows)
    r.to_parquet("survive_search.parquet")
    cols = ["stop xATR", "skip if stop >$", "account", "eval MNQ", "funded MNQ", "pass %", "survive 1yr %",
            "worst start-yr %", "median eval days", "payouts in yr $", "trades/yr", "1-MNQ total $", "1-MNQ maxDD $"]
    print("\nBest survival per account size:")
    print(r.sort_values("survive 1yr %", ascending=False).groupby("account").head(4)[cols]
          .sort_values(["account", "survive 1yr %"], ascending=[True, False]).round(0).to_string(index=False))
    print("\nTop 15 by WORST start year (consistency):")
    print(r.sort_values(["worst start-yr %", "survive 1yr %"], ascending=False).head(15)[cols + [f"s{y}" for y in range(2020, 2026)]]
          .round(0).to_string(index=False))


if __name__ == "__main__":
    main()
