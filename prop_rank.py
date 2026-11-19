"""Rank prop_search.parquet by in-sample steadiness (neighbour-smoothed), then show 2024-26 results."""
import numpy as np
import pandas as pd

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
r = pd.read_parquet("prop_search.parquet")
r["key"] = list(zip(r.anchor, r.start, r.len, r.exit, r.tp, r.sl))
tps = sorted(r.tp.unique()); sls = sorted(r.sl.unique())
r["ti"] = r.tp.map({v: i for i, v in enumerate(tps)}); r["si"] = r.sl.map({v: i for i, v in enumerate(sls)})
idx = r.set_index(["anchor", "start", "len", "exit", "ti", "si"])["IS_sharpe"]
nb = []
for dst, dl, dt, ds in [(15, 0, 0, 0), (-15, 0, 0, 0), (0, 15, 0, 0), (0, -15, 0, 0), (0, 0, 1, 0), (0, 0, -1, 0),
                        (0, 0, 0, 1), (0, 0, 0, -1)]:
    k = pd.MultiIndex.from_arrays([r.anchor, r.start + dst, r.len + dl, r.exit, r.ti + dt, r.si + ds])
    nb.append(idx.reindex(k).to_numpy())
V = np.vstack([r.IS_sharpe.to_numpy()] + nb)
r["IS_sharpe_nbr"] = np.nanmean(V, axis=0)
r["nbr_min"] = np.nanmin(V, axis=0)

hh = lambda m: f"{m // 60:02d}:{m % 60:02d}"
r["window"] = r.anchor.str[:3] + " " + r.start.map(hh) + "+" + r.len.astype(str) + " -> " + r.exit.map(hh)
r["tp_"] = r.tp.map(lambda v: "none" if v > 50 else f"{v}xATR"); r["sl_"] = r.sl.astype(str) + "xATR"
cols = ["window", "tp_", "sl_", "trades", "winrate", "IS_sharpe", "IS_sharpe_nbr", "nbr_min", "IS_posmo", "IS_top10",
        "IS_tot", "VAL_sharpe", "VAL_tot", "VAL_posmo", "HOLD_sharpe", "HOLD_tot", "maxdd", "worst_day"]

E = r[(r.anchor == "London") & (r.start == 450) & (r.len == 60) & (r.exit == 1255) & (r.tp > 50) & (r.sl == 1.0)]
print("Preset E for reference:")
print(E[cols].round(2).to_string(index=False))

cand = r[(r.trades >= 800) & (r.IS_tot > 0) & (r.IS_top10 < 0.6)].sort_values("IS_sharpe_nbr", ascending=False)
top = cand.drop_duplicates(["anchor", "start", "len"]).head(15)
print("\nTop 15 by neighbour-smoothed 2020-23 Sharpe (one per window), with 2024-25 and 2026 results:")
print(top[cols].round(2).to_string(index=False))

t200 = cand.head(200)
print(f"\nTop 200 by IS steadiness: VAL Sharpe>0 {(t200.VAL_sharpe > 0).mean():.0%} (median {t200.VAL_sharpe.median():.2f}), "
      f"HOLD Sharpe>0 {(t200.HOLD_sharpe > 0).mean():.0%} (median {t200.HOLD_sharpe.median():.2f})")
print(f"All variants: VAL Sharpe>0 {(r.VAL_sharpe > 0).mean():.0%}, HOLD Sharpe>0 {(r.HOLD_sharpe > 0).mean():.0%}")
for a in ["London", "NewYork"]:
    t = cand[cand.anchor == a].head(100)
    print(f"  {a}: top-100 IS -> VAL Sharpe median {t.VAL_sharpe.median():.2f} ({(t.VAL_sharpe > 0).mean():.0%} >0), "
          f"HOLD median {t.HOLD_sharpe.median():.2f} ({(t.HOLD_sharpe > 0).mean():.0%} >0)")
cand.head(400).drop(columns=["key"]).to_parquet("prop_candidates.parquet")
