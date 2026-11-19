"""One-account survival search: buy ONE evaluation, pass it, keep the funded account alive.

For each variant (prop_search grid + preset E) and contract count, start an evaluation every 5 trading days.
  Evaluation: EOD trailing drawdown (checked against open loss), profit target, best day <= 50% of profit,
              must pass within 252 trading days (else counted as a failure).
  Funded:     same drawdown, locks at start; payout after 5 days >= min daily profit and balance >= DD + $500,
              withdraw down to DD above start (capped), 90% split. Run 252 trading days.
  Success = passed AND funded account still alive after 252 days.
Selection on starts in 2020-2023 (IS); check on starts in 2024-2025 (OOS; funded year may run into 2026).

Usage: python single_acct.py  -> single_acct_results.parquet
"""
import time

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s
from prop_search import block, TPM, SLM, GRIDS

ACCTS = {"50K": (2000.0, 3000.0, 2000.0, 150.0), "150K": (4500.0, 9000.0, 5000.0, 250.0)}


@njit
def sim(pnl, mae, starts, n, dd, tgt, cap, mind):
    """pnl/mae: [day] $ per 1 MNQ (nan = no trade). Returns per start: passed, eval days, funded alive days, payouts $."""
    ns = len(starts); N = len(pnl)
    out = np.zeros((ns, 4))
    for i in range(ns):
        s0 = starts[i]
        bal = 0.0; thr = -dd; best = 0.0; passed = 0; d = s0; k = 0
        while d < N and k < 252:
            p = pnl[d]
            if p == p:
                a = mae[d] * n; p = p * n
                if bal + a <= thr or bal + p <= thr:
                    break
                bal += p
                t2 = bal - dd
                if t2 > thr:
                    thr = t2 if t2 < 0.0 else (0.0 if thr < 0.0 else thr)
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
                a = mae[d] * n; p = p * n
                if bal + a <= thr or bal + p <= thr:
                    break
                bal += p
                t2 = bal - dd
                if t2 > thr:
                    thr = t2 if t2 < 0.0 else (0.0 if thr < 0.0 else thr)
                if p >= mind: qual += 1
                if qual >= 5 and bal >= dd + 500.0:
                    w = min(cap, bal - dd)
                    bal -= w; paid += w * 0.9; qual = 0
            d += 1; alive += 1
        out[i, 2] = alive; out[i, 3] = paid
    return out


def score(out, is_mask, oos_mask, fee):
    res = {}
    for tag, m in (("IS", is_mask), ("OOS", oos_mask)):
        o = out[m]
        passed = o[:, 0] == 1
        res[f"{tag}_pass"] = passed.mean()
        res[f"{tag}_success"] = (passed & (o[:, 2] >= 252)).mean()
        res[f"{tag}_alive6m"] = (passed & (o[:, 2] >= 126)).mean()
        res[f"{tag}_paid"] = o[:, 3].mean() - fee           # expected payouts minus the one fee
        res[f"{tag}_eval_days"] = np.median(o[passed, 1]) if passed.any() else np.nan
        res[f"{tag}_anypay"] = (o[:, 3] > 0).mean()
    return res


def main():
    df = pd.read_parquet("nq_1m.parquet")
    t0 = time.time()
    rows = []
    for anchor, (tz, starts_l, lens, exits) in GRIDS.items():
        days, O, H, L, C = s.day_matrix(df, tz)
        wk = days.weekday < 5
        days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
        rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
        atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
        st = np.arange(20, len(days) - 300, 5)
        sd = days[st]
        is_mask = sd.year <= 2023
        oos_mask = (sd.year >= 2024) & (sd.year <= 2025)
        for rs_ in starts_l:
            for ln in lens:
                ex_ok = np.array([e for e in exits if e > rs_ + ln + 15], dtype=np.int64)
                p, m = block(O, H, L, C, rs_, rs_ + ln, ex_ok, atr, TPM, SLM, 1.0)
                usd = p.astype(np.float64) * 2 - 1.24; mus = m.astype(np.float64) * 2 - 1.24
                for ei, ex in enumerate(ex_ok):
                    for ti, tp in enumerate(TPM):
                        for si, sl in enumerate(SLM):
                            pv = usd[:, ei, ti, si]; mv = mus[:, ei, ti, si]
                            for acct, (dd, tgt, cap, mind) in ACCTS.items():
                                fee = 150.0 if acct == "50K" else 350.0
                                for n in ((1, 2) if acct == "50K" else (1, 2, 3, 5)):
                                    out = sim(pv, mv, st, n, dd, tgt, cap, mind)
                                    rows.append({"anchor": anchor, "start": rs_, "len": ln, "exit": int(ex), "tp": tp,
                                                 "sl": sl, "acct": acct, "MNQ": n,
                                                 **score(out, is_mask, oos_mask, fee)})
            print(f"{anchor} {rs_ // 60:02d}:{rs_ % 60:02d} done {time.time() - t0:.0f}s, {len(rows):,} rows", flush=True)
    r = pd.DataFrame(rows)
    r.to_parquet("single_acct_results.parquet")
    print("saved", len(r))


if __name__ == "__main__":
    main()
