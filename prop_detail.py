"""Evaluation and funded-account detail for preset E under LucidFlex/Topstep-style rules
(end-of-day trailing drawdown; 50% best-day consistency in the evaluation; none when funded).

Evaluation: started on every trading day 2020 - 2026; runs until pass or bust (no time limit).
Funded:     started the day after each pass; runs up to 252 trading days or until bust.
            Payout: once there are 5 qualifying days (>= min daily profit) since the last payout and
            the balance is >= DD + $500 above start, withdraw down to DD above start (capped), 90% split.

Usage: python prop_detail.py
"""
import json

import numpy as np
import pandas as pd
from numba import njit

SETUPS = {  # name: (MNQ, DD, target, payout cap, min qualifying day profit)
    "50K x 2 MNQ": (2, 2000.0, 3000.0, 2000.0, 150.0),
    "150K x 5 MNQ": (5, 4500.0, 9000.0, 5000.0, 250.0),
}
SPLIT = 0.90
HOR = 252


@njit
def run_eval(pnl, mae, s0, n, dd, target, cons):
    bal = 0.0; thr = -dd; best = 0.0; days = 0
    for d in range(s0, len(pnl)):
        p = pnl[d]
        days += 1
        if p != p:
            continue
        a = mae[d] * n; p = p * n
        if bal + a <= thr:
            return -1, days, d
        bal += p
        if bal <= thr:
            return -1, days, d
        t2 = bal - dd
        if t2 > thr: thr = min(t2, 0.0) if thr < 0 else thr
        if p > best: best = p
        if bal >= target and best <= cons * bal:
            return 1, days, d
    return 0, days, len(pnl) - 1


@njit
def run_funded(pnl, mae, s0, n, dd, cap, minday, hor, split):
    """Returns (cum payouts per day [hor], balance per day [hor], bust day index or -1, n payouts)."""
    cum = np.full(hor, np.nan); balarr = np.full(hor, np.nan)
    bal = 0.0; thr = -dd; paid = 0.0; qual = 0; npay = 0
    for k in range(hor):
        d = s0 + k
        if d >= len(pnl):
            return cum, balarr, -2, npay
        p = pnl[d]
        if p == p:
            a = mae[d] * n; p = p * n
            if bal + a <= thr or bal + p <= thr:
                cum[k] = paid; balarr[k] = thr
                return cum, balarr, k, npay
            bal += p
            t2 = bal - dd
            if t2 > thr: thr = min(t2, 0.0) if thr < 0 else thr
            if p >= minday:
                qual += 1
            if qual >= 5 and bal >= dd + 500.0:
                w = min(cap, bal - dd)
                paid += w * split; bal -= w; qual = 0; npay += 1
        cum[k] = paid; balarr[k] = bal
    return cum, balarr, -1, npay


def main():
    df = pd.read_parquet("prop_days.parquet")
    days = df.index
    pnl = df["E_pnl"].to_numpy(); mae = df["E_mae"].to_numpy()
    out = {}
    for name, (n, dd, tgt, cap, mind) in SETUPS.items():
        res = np.array([run_eval(pnl, mae, s0, n, dd, tgt, 0.5) for s0 in range(15, len(pnl) - 60)])
        outc, ndays, endd = res[:, 0], res[:, 1], res[:, 2]
        done = outc != 0
        pas = outc == 1; bust = outc == -1
        print(f"\n===== {name} (DD ${dd:,.0f}, target ${tgt:,.0f}) =====")
        print(f"Evaluations simulated: {len(outc):,}  (started every trading day)")
        print(f"  Pass {pas[done].mean():.0%}   Bust {bust[done].mean():.0%}   (unfinished at data end: {(~done).sum()})")
        for lab, m in [("passed", pas), ("busted", bust)]:
            q = np.percentile(ndays[m], [25, 50, 75, 90])
            print(f"  Trading days in eval when {lab}: median {q[1]:.0f} (25-75%: {q[0]:.0f}-{q[2]:.0f}, 90%: {q[3]:.0f})")
        # expected attempts until a pass and total eval time
        p_pass = pas[done].mean()
        print(f"  Average evaluations bought per funded account: {1 / p_pass:.1f}")
        # chain: from each start, keep retrying until pass; measure days until funded
        chain = []
        for s0 in range(15, len(pnl) - 300, 5):
            s, tot = s0, 0
            while s < len(pnl) - 1:
                o, k, e = run_eval(pnl, mae, s, n, dd, tgt, 0.5)
                tot += k
                if o == 1:
                    chain.append(tot); break
                if o == 0:
                    break
                s = e + 1
        chain = np.array(chain)
        q = np.percentile(chain, [25, 50, 75, 90])
        print(f"  Days from first purchase to funded (retrying after busts): median {q[1]:.0f} trading days "
              f"(~{q[1] / 21:.1f} months), 25-75%: {q[0]:.0f}-{q[2]:.0f}, 90%: {q[3]:.0f}")

        # funded accounts after each pass
        pass_days = np.unique(endd[pas]) + 1
        pass_days = pass_days[pass_days < len(pnl) - 20]
        C = []; B = []; bustk = []; npays = []
        for s0 in pass_days:
            c, b, k, npay = run_funded(pnl, mae, s0, n, dd, cap, mind, HOR, SPLIT)
            if k == -2:
                continue
            C.append(c); B.append(b); bustk.append(k); npays.append(npay)
        C = np.array(C); bustk = np.array(bustk); npays = np.array(npays)
        full = C.copy()
        for i in range(len(full)):  # after bust, payouts stay flat
            last = np.nan
            for k in range(HOR):
                if np.isnan(full[i, k]):
                    full[i, k] = last
                else:
                    last = full[i, k]
        alive = np.array([(bustk == -1) | (bustk > k) for k in range(HOR)]).mean(axis=1)
        tot = full[:, -1]
        valid = ~np.isnan(tot)
        print(f"  Funded accounts simulated: {len(C)} (one per distinct pass day)")
        print(f"  Still alive after 1 / 3 / 6 / 12 months: {alive[20]:.0%} / {alive[62]:.0%} / {alive[125]:.0%} / {alive[-1]:.0%}")
        bk = bustk[bustk >= 0]
        if len(bk):
            print(f"  Busted funded accounts: median life {np.median(bk):.0f} trading days")
        print(f"  Funded accounts that got at least one payout: {(npays > 0).mean():.0%}")
        q = np.nanpercentile(tot[valid], [10, 25, 50, 75, 90])
        print(f"  Total payouts per funded account over up to 12 months (after 90% split): "
              f"median ${q[2]:,.0f}  (25-75%: ${q[1]:,.0f}-${q[3]:,.0f}; 10%: ${q[0]:,.0f}; 90%: ${q[4]:,.0f}); "
              f"mean ${np.nanmean(tot[valid]):,.0f}")
        first = []
        for i in range(len(C)):
            nz = np.where(np.nan_to_num(C[i]) > 0)[0]
            if len(nz): first.append(nz[0] + 1)
        if first:
            print(f"  Days to first payout (if any): median {np.median(first):.0f} trading days")
        sel = full[valid]
        out[name] = {"p25": np.nanpercentile(sel, 25, axis=0).round(0).tolist(),
                     "p50": np.nanpercentile(sel, 50, axis=0).round(0).tolist(),
                     "p75": np.nanpercentile(sel, 75, axis=0).round(0).tolist(),
                     "mean": np.nanmean(sel, axis=0).round(0).tolist(),
                     "alive": (alive * 100).round(1).tolist(),
                     "pass": round(float(pas[done].mean()) * 100), "bust": round(float(bust[done].mean()) * 100),
                     "eval_med_pass": float(np.median(ndays[pas])), "eval_med_bust": float(np.median(ndays[bust])),
                     "to_funded_med": float(np.median(chain)), "evals_per_funded": round(1 / p_pass, 1),
                     "payout_med": float(q[2]), "payout_mean": float(np.nanmean(tot[valid])),
                     "alive12": float(alive[-1] * 100)}
    json.dump(out, open("prop_detail.json", "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
