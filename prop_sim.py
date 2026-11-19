"""Replay presets D/E through prop-firm rule types, as one-year campaigns from many start dates.

Campaign: buy evaluation -> trade until pass or fail -> funded account -> payouts -> if funded account
breaches, buy a new evaluation. Runs 252 trading days from each start (every 5th day, 2020 - Nov 2025).

Drawdown types
  EOD      : threshold = max end-of-day balance - DD (never down), checked intraday against open loss
  intraday : threshold follows peak open equity (unrealized included) - DD
Both lock at the starting balance once reached. Worst open loss is assumed to come before the best
open profit on the same day (conservative for intraday trailing).

Payout policy (same for every firm so the rule structure is what's compared): every 10 trading days,
if the funded account is >= DD + $500 above start and the consistency rule (best day since last payout
<= X% of profit since last payout) is met, withdraw down to DD above start, capped per payout.

Usage: python prop_sim.py
"""
import numpy as np
import pandas as pd
from numba import njit

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)

SIZES = {"50K": (2000.0, 3000.0, 2000.0), "100K": (3000.0, 6000.0, 3000.0), "150K": (4500.0, 9000.0, 5000.0)}
# name: (eval mode, eval consistency, funded mode, funded consistency, split, fee per eval month, activation, firms)
RULES = {
    "EOD eval 50% -> EOD funded, no consistency": (0, 0.50, 0, 1.0, 0.90, 150, 100,
        "Topstep*, Lucid Flex*, MyFundedFutures*"),
    "EOD eval 40% -> EOD funded, no consistency": (0, 0.40, 0, 1.0, 0.90, 200, 0,
        "Tradeify Select*, Alpha Futures Advanced*"),
    "EOD eval none -> EOD funded 50%": (0, 1.0, 0, 0.50, 0.90, 150, 100, "Apex (EOD)*"),
    "EOD eval 50% -> INTRADAY funded, no consistency": (0, 0.50, 1, 1.0, 0.80, 300, 130, "Take Profit Trader PRO*"),
    "INTRADAY eval none -> INTRADAY funded 50%": (1, 1.0, 1, 0.50, 0.90, 150, 100, "Apex (intraday)*"),
}
HORIZON = 252


@njit
def campaign(pnl, mae, mfe, start, horizon, n, dd, target, cap, emode, econs, fmode, fcons, split,
             fee_month, activation):
    """Returns (net $, payouts $, fees $, evals bought, evals passed, funded breaches)."""
    end = min(start + horizon, len(pnl))
    phase = 0  # 0 eval, 1 funded
    bal = 0.0; thr = -dd; best = 0.0; days_in = 0
    fees = fee_month; evals = 1; passed = 0; breaches = 0; paid = 0.0
    since_pay = 0; best_since = 0.0; prof_since = 0.0
    for d in range(start, end):
        p = pnl[d]
        days_in += 1
        if phase == 0 and days_in % 21 == 0:
            fees += fee_month
        if p != p:
            continue
        a = mae[d] * n; f = mfe[d] * n; p = p * n
        mode = emode if phase == 0 else fmode
        # intraday open loss
        if bal + a <= thr:
            failed = True
        else:
            failed = False
            if mode == 1:
                t2 = bal + f - dd
                if t2 > thr: thr = min(t2, 0.0) if thr < 0.0 else thr
            bal += p
            if bal <= thr:
                failed = True
            elif mode == 0:
                t2 = bal - dd
                if t2 > thr: thr = min(t2, 0.0) if thr < 0.0 else thr
        if failed:
            if phase == 1:
                breaches += 1
            phase = 0; bal = 0.0; thr = -dd; best = 0.0; days_in = 0
            fees += fee_month; evals += 1
            continue
        if phase == 0:
            if p > best: best = p
            if bal >= target and best <= econs * bal:
                phase = 1; passed += 1; fees += activation
                bal = 0.0; thr = -dd; since_pay = 0; best_since = 0.0; prof_since = 0.0; days_in = 0
        else:
            since_pay += 1
            prof_since += p
            if p > best_since: best_since = p
            if since_pay >= 10 and bal >= dd + 500.0 and best_since <= fcons * max(prof_since, 1e-9):
                w = min(cap, bal - dd)
                paid += w * split
                bal -= w
                since_pay = 0; best_since = 0.0; prof_since = 0.0
    return paid - fees, paid, fees, evals, passed, breaches


def main():
    df = pd.read_parquet("prop_days.parquet")
    rows = []
    for preset in ("D", "E"):
        pnl = df[f"{preset}_pnl"].to_numpy(); mae = df[f"{preset}_mae"].to_numpy(); mfe = df[f"{preset}_mfe"].to_numpy()
        starts = np.arange(15, len(pnl) - HORIZON, 5)
        for rname, (em, ec, fm, fc, split, fee, act, firms) in RULES.items():
            for size, (dd, tgt, cap) in SIZES.items():
                for n in range(1, 9):
                    res = np.array([campaign(pnl, mae, mfe, s0, HORIZON, n, dd, tgt, cap, em, ec, fm, fc, split,
                                             fee * (dd / 4500 if size != "150K" else 1), act) for s0 in starts])
                    net, paid, fees, ev, ps, br = res.T
                    rows.append({"preset": preset, "rules": rname, "firms": firms, "size": size, "MNQ": n,
                                 "median net/yr": np.median(net), "mean net/yr": net.mean(),
                                 "% years net>0": (net > 0).mean() * 100, "worst year": net.min(),
                                 "evals bought": ev.mean(), "pass rate": ps.sum() / ev.sum() * 100,
                                 "funded blowups": br.mean(), "fees": fees.mean()})
    r = pd.DataFrame(rows)
    r.to_csv("prop_sim_results.csv", index=False)
    show = r.sort_values("median net/yr", ascending=False)
    cols = ["preset", "rules", "size", "MNQ", "median net/yr", "mean net/yr", "% years net>0", "worst year",
            "evals bought", "pass rate", "funded blowups", "fees"]
    print("Top 25 combinations by median net profit per one-year campaign (after fees and split):")
    print(show[cols].head(25).round(0).to_string(index=False))
    print("\nBest size/contracts per rule type (preset E):")
    e = r[r.preset == "E"].sort_values("median net/yr", ascending=False).groupby("rules").head(1)
    print(e[["rules", "firms", "size", "MNQ", "median net/yr", "% years net>0", "worst year", "pass rate",
             "funded blowups"]].round(0).to_string(index=False))
    print("\nPreset E, 150K, 1 MNQ, every rule type:")
    print(r[(r.preset == "E") & (r["size"] == "150K") & (r.MNQ == 1)][cols].round(0).to_string(index=False))
    print("\nPreset E, 50K, 1 MNQ, every rule type:")
    print(r[(r.preset == "E") & (r["size"] == "50K") & (r.MNQ == 1)][cols].round(0).to_string(index=False))


if __name__ == "__main__":
    main()
