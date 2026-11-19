"""Neighbourhood + per-year check of the NY ORB-scalp candidate from prop_strat.parquet."""
import pandas as pd

pd.set_option("display.width", 260)
pd.set_option("display.max_rows", 200)
r = pd.read_parquet("prop_strat.parquet")
YR = [f"s{y}" for y in range(2020, 2026)]
q = r[(r.family == "ORB scalp") & r.window.str.startswith("NY") & (r.dayloss == 0) & (r.daytp == 0) & (r.K == 1)]
cols = ["window", "exit", "tp", "sl", "acct", "eval MNQ", "funded MNQ", "IS surv %", "OOS surv %", "payouts $ (survivors)",
        "1-MNQ total $", "1-MNQ maxDD $", "IS $", "OOS $", "2026 $"] + YR
best = q[(q.acct == "50K") & (q["eval MNQ"] == 2) & (q["funded MNQ"] == 1)]
print("NY ORB scalp, K=1, no daily caps, 50K, eval 2 -> funded 1 MNQ, every window/exit/TP/SL:")
print(best.sort_values(["window", "exit", "tp", "sl"])[cols].round(0).to_string(index=False))
g = q.groupby(["acct", "eval MNQ", "funded MNQ"])[["IS surv %", "OOS surv %"]].agg(["mean", "max"]).round(0)
print("\nAcross all NY ORB-scalp settings, mean / max survival by account and size:")
print(g.to_string())
