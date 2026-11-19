"""Rank single-account survival results (neighbour-smoothed IS success), show OOS (2024-25 starts)."""
import numpy as np
import pandas as pd

pd.set_option("display.width", 280); pd.set_option("display.max_columns", 30)
r = pd.read_parquet("single_acct_results.parquet")
tps = sorted(r.tp.unique()); sls = sorted(r.sl.unique())
r["ti"] = r.tp.map({v: i for i, v in enumerate(tps)}); r["si"] = r.sl.map({v: i for i, v in enumerate(sls)})
key = ["anchor", "acct", "MNQ", "exit"]
idx = r.set_index(key + ["start", "len", "ti", "si"])["IS_success"]
nb = []
for dst, dl, dt, ds in [(15, 0, 0, 0), (-15, 0, 0, 0), (0, 15, 0, 0), (0, -15, 0, 0), (0, 0, 1, 0), (0, 0, -1, 0),
                        (0, 0, 0, 1), (0, 0, 0, -1)]:
    k = pd.MultiIndex.from_arrays([r[c] for c in key] + [r.start + dst, r.len + dl, r.ti + dt, r.si + ds])
    nb.append(idx.reindex(k).to_numpy())
V = np.vstack([r.IS_success.to_numpy()] + nb)
r["IS_success_nbr"] = np.nanmean(V, axis=0)
r["nbr_min"] = np.nanmin(V, axis=0)
hh = lambda m: f"{m // 60:02d}:{m % 60:02d}"
r["window"] = r.anchor.str[:3] + " " + r.start.map(hh) + "+" + r.len.astype(str) + "->" + r.exit.map(hh)
r["tp_"] = r.tp.map(lambda v: "none" if v > 50 else f"{v}x"); r["sl_"] = r.sl.astype(str) + "x"
cols = ["acct", "MNQ", "window", "tp_", "sl_", "IS_pass", "IS_success", "IS_success_nbr", "nbr_min", "IS_alive6m",
        "IS_anypay", "IS_paid", "IS_eval_days", "OOS_pass", "OOS_success", "OOS_alive6m", "OOS_anypay", "OOS_paid",
        "OOS_eval_days"]
E = r[(r.anchor == "London") & (r.start == 450) & (r.len == 60) & (r.exit == 1255) & (r.tp > 50) & (r.sl == 1.0)]
print("Preset E reference:")
print(E[cols].round(2).to_string(index=False))
for acct in ("50K", "150K"):
    a = r[(r.acct == acct) & (r.IS_pass >= 0.2)].sort_values("IS_success_nbr", ascending=False)
    print(f"\n===== {acct}: top 12 by neighbour-smoothed IS success (one per window/size) =====")
    print(a.drop_duplicates(["MNQ", "anchor", "start", "len"]).head(12)[cols].round(2).to_string(index=False))
    t = a.head(100)
    print(f"Top 100 IS -> OOS success median {t.OOS_success.median():.0%} (IS median {t.IS_success.median():.0%}); "
          f"OOS pass median {t.OOS_pass.median():.0%}")
r.to_parquet("single_acct_ranked.parquet")
