"""Same real-life cycle as prop_lifecycle.py, for a 150K account:
$4,500 end-of-day trailing drawdown, $9,000 target, payout days need >= $250, max $5,000 per payout,
keep $4,500 above start after each payout, 90% split. Runs with a $150 and a $350 evaluation fee.

Usage: python prop_lifecycle_150k.py
"""
import json

import numpy as np
import pandas as pd

import prop_lifecycle as pl

pl.DD, pl.TGT, pl.CAP, pl.MIND = 4500.0, 9000.0, 5000.0, 250.0
SIZES = [(5, 5), (5, 3), (5, 2), (5, 1), (3, 3), (8, 8)]


def main():
    df = pd.read_parquet("prop_days.parquet")
    pnl = df["E_pnl"].to_numpy(); mae = df["E_mae"].to_numpy(); dates = df.index
    start = int(np.searchsorted(dates, pd.Timestamp("2020-01-20")))
    out = {}
    summary = []
    for fee in (150.0, 350.0):
        pl.FEE = fee
        for ne, nf in SIZES:
            curve, events = pl.lifecycle(pnl, mae, dates, start, ne, nf)
            ev = pd.DataFrame(events, columns=["date", "kind", "amount"])
            ev["year"] = pd.to_datetime(ev.date).dt.year
            finals = []
            for m in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
                s0 = int(np.searchsorted(dates, m))
                c, _ = pl.lifecycle(pnl, mae, dates, s0, ne, nf)
                finals.append(c[-1] / ((len(pnl) - s0) / 252))
            finals = np.array(finals)
            pays = ev[ev.kind == "payout"]
            summary.append({"fee": fee, "eval MNQ": ne, "funded MNQ": nf,
                            "bought": int((ev.kind == "buy").sum()), "passed": int((ev.kind == "pass").sum()),
                            "payouts": len(pays), "paid": round(pays.amount.sum()),
                            "fees": round((ev.kind == "buy").sum() * fee), "net": round(ev.amount.sum()),
                            "net ex-2026": round(ev[ev.year < 2026].amount.sum()),
                            "worst dip": round((np.maximum.accumulate(curve[start:]) - curve[start:]).max()),
                            "net/yr by start month (median)": round(np.median(finals)),
                            "range": f"{finals.min():,.0f} to {finals.max():,.0f}",
                            "% starts positive": round((finals > 0).mean() * 100)})
            if fee == 150.0 and (ne, nf) in [(5, 5), (5, 2), (5, 1)]:
                pl.summarise(events, f"150K, eval {ne} MNQ, funded {nf} MNQ, fee ${fee:.0f}")
                s = pd.Series(curve[start:], index=dates[start:]).resample("W-FRI").last().dropna()
                out[f"{ne}/{nf}"] = s.round(0).astype(int).tolist()
                out["d"] = [x.strftime("%Y-%m-%d") for x in s.index]
    pd.set_option("display.width", 250)
    print("\n===== All 150K variants =====")
    print(pd.DataFrame(summary).to_string(index=False))
    json.dump(out, open("prop_lifecycle_150k.json", "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
