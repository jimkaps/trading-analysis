"""Within the morning region, choose by neighbourhood-smoothed 2020-2025 P&L; report 2026 as out-of-sample."""
import sys

import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
r = pd.read_parquet(sys.argv[1])
for c in ["anchor", "tp", "sl", "dir", "trend", "width"]:
    r[c] = r[c].astype(str)
Y = [f"y{y}" for y in range(2020, 2027)]
r["SEL"] = r[Y[:6]].sum(axis=1)
r["HOLD"] = r["y2026"]
r["posyrs_sel"] = (r[Y[:6]] > 0).sum(axis=1)
r["winrate"] = r.wins / r.trades

starts = [420, 435, 450, 465, 480]
lens = [30, 45, 60, 90]
tps = ["1.0%", "1.25%", "1.5%", "2.0%", "none"]
sls = ["0.25%", "0.35%", "0.5%", "0.75%", "1.0%"]
exits = [1080, 1110, 1170, 1255]
q = r[(r.anchor == "London") & r.start.isin(starts) & r.len.isin(lens) & r.exit.isin(exits) & r.tp.isin(tps)
      & r.sl.isin(sls) & (r.dir == "both") & (r.trend == "none") & (r.width == "all")].copy()
q["si"] = q.start.map({v: i for i, v in enumerate(starts)})
q["li"] = q.len.map({v: i for i, v in enumerate(lens)})
q["ti"] = q.tp.map({v: i for i, v in enumerate(tps)})
q["sli"] = q.sl.map({v: i for i, v in enumerate(sls)})
q["ei"] = q.exit.map({v: i for i, v in enumerate(exits)})
dims = ["si", "li", "ti", "sli", "ei"]
idx = q.set_index(dims)["SEL"]
vals = []
for d in dims:
    for s in (-1, 1):
        k = q[dims].copy(); k[d] = k[d] + s
        vals.append(idx.reindex(pd.MultiIndex.from_frame(k)).to_numpy())
V = np.vstack([q.SEL.to_numpy()] + vals)
q["SEL_nbr"] = np.nanmean(V, axis=0)
q["nbr_min"] = np.nanmin(V, axis=0)
q["nbr_n"] = (~np.isnan(V)).sum(axis=0)
q = q[q.nbr_n >= 8]

top = q[q.posyrs_sel >= 5].sort_values("SEL_nbr", ascending=False).head(12)
hh = lambda m: f"{m // 60:02d}:{m % 60:02d}"
top = top.assign(range=top.start.map(hh) + "-" + (top.start + top.len).map(hh), ex=top.exit.map(hh))
cols = ["range", "ex", "tp", "sl", "trades", "winrate", "maxdd", "SEL", "SEL_nbr", "nbr_min", "HOLD"] + Y
print("Chosen on 2020-2025 (neighbourhood-smoothed); 2026 = out-of-sample:")
print(top[cols].round(2).to_string(index=False))
print(f"\nRegion overall: {len(q)} settings, 2026>0 in {(q.HOLD > 0).mean():.0%}; "
      f"top-12 2026>0 in {(top.HOLD > 0).mean():.0%}, median ${top.HOLD.median():,.0f}")
