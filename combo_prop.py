"""Combine NQ_E, NQ_NY and GC_E streams and run the real-life prop cycle with a 6-payout cap per account.

Ranking uses 2020-2025 only (cycles stop at 31 Dec 2025) so 2026 cannot drive the choice; 2026 is shown separately.
Usage: python combo_prop.py
"""
import itertools

import numpy as np
import pandas as pd

import prop_lifecycle as pl

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30)
ACCTS = {"50K": (2000.0, 3000.0, 2000.0, 150.0, 150.0), "150K": (4500.0, 9000.0, 5000.0, 250.0, 350.0)}


def load():
    st = pd.read_parquet("streams.parquet").fillna(0.0)
    return st


def run_combo(st, w, acct, end, maxpay=6):
    dd, tgt, cap, mind, fee = ACCTS[acct]
    pl.DD, pl.TGT, pl.CAP, pl.MIND, pl.FEE, pl.MAXPAY = dd, tgt, cap, mind, fee, maxpay
    sub = st[st.index <= end]
    pnl = sum(sub[f"{k}_pnl"].to_numpy() * n for k, n in w.items())
    mae = sum(np.minimum(sub[f"{k}_mae"].to_numpy(), 0) * n for k, n in w.items())   # all open together: worst case
    traded = sum((sub[f"{k}_pnl"] != 0).to_numpy() * 1 for k in w)
    pnl = np.where(traded > 0, pnl, np.nan)
    dates = sub.index
    finals, yrs_pos, top_share = [], [], []
    for m in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
        s0 = int(np.searchsorted(dates, m))
        c, ev = pl.lifecycle(pnl, mae, dates, s0, 1, 1)
        finals.append(c[-1] / ((len(pnl) - s0) / 252))
    c, ev = pl.lifecycle(pnl, mae, dates, int(np.searchsorted(dates, pd.Timestamp("2020-01-20"))), 1, 1)
    e = pd.DataFrame(ev, columns=["date", "kind", "amount"])
    e["acct"] = (e.kind == "pass").cumsum()
    e["year"] = pd.to_datetime(e.date).dt.year
    pay = e[e.kind == "payout"]
    yr = e.groupby("year").amount.sum()
    share = pay.groupby("acct").amount.sum().max() / pay.amount.sum() if len(pay) else np.nan
    return {"net/yr median": np.median(finals), "net/yr worst start": np.min(finals),
            "net 2020 start": c[-1], "years positive": f"{(yr > 0).sum()}/{len(yr)}", "worst year": yr.min(),
            "evals": int((e.kind == "buy").sum()), "passes": int((e.kind == "pass").sum()),
            "payouts": len(pay), "top account share": share,
            "worst dip": (np.maximum.accumulate(c) - c).max()}, yr


def main():
    st = load()
    end = pd.Timestamp("2025-12-31")
    rows = []
    grids = {
        "E only": [{"NQ_E": a} for a in range(1, 7)],
        "E + NY": [{"NQ_E": a, "NQ_NY": b} for a, b in itertools.product(range(1, 6), range(1, 6))],
        "E + gold": [{"NQ_E": a, "GC_E": c} for a, c in itertools.product(range(1, 6), range(1, 4))],
        "E + NY + gold": [{"NQ_E": a, "NQ_NY": b, "GC_E": c}
                          for a, b, c in itertools.product(range(1, 6), range(1, 6), range(1, 4))],
    }
    for acct in ACCTS:
        for gname, ws in grids.items():
            for w in ws:
                res, _ = run_combo(st, w, acct, end)
                rows.append({"account": acct, "combo": gname,
                             "contracts": " ".join(f"{k}x{n}" for k, n in w.items()), **res})
        print(f"{acct} done", flush=True)
    r = pd.DataFrame(rows)
    r.to_csv("combo_prop_results.csv", index=False)
    for acct in ACCTS:
        a = r[r.account == acct]
        best = a.sort_values("net/yr median", ascending=False).groupby("combo").head(2)
        print(f"\n===== {acct}, 2020-2025, 6-payout cap, fee ${ACCTS[acct][4]:.0f}: best 2 per combo =====")
        print(best.round(2).to_string(index=False))
    # 2026 check for the top pick per account and combo
    print("\n===== Same picks run through 2026 (2026 not used to choose) =====")
    for acct in ACCTS:
        a = r[r.account == acct]
        for gname in grids:
            row = a[a.combo == gname].sort_values("net/yr median", ascending=False).iloc[0]
            w = {k: int(n) for k, n in (t.split("x") for t in row.contracts.split())}
            res, yr = run_combo(st, w, acct, pd.Timestamp("2026-12-31"))
            print(f"{acct} {gname:14s} {row.contracts:28s} yearly net: " +
                  ", ".join(f"{y}: {v:,.0f}" for y, v in yr.items()) +
                  f" | top account share {res['top account share']:.0%}")


if __name__ == "__main__":
    main()
