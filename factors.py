"""Average effect of each design choice across all variants, per period.

Paired comparisons: each filter vs. the same variant without it, so the effect is
measured on thousands of matched pairs rather than one cherry-picked winner.
"""
import sys

import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
r = pd.read_parquet(sys.argv[1])
for c in ["anchor", "tp", "sl", "dir", "trend", "width"]:
    r[c] = r[c].astype(str)
Y = [f"y{y}" for y in range(2020, 2027)]
r["IS"] = r[Y[:4]].sum(axis=1)
r["VAL"] = r[Y[4:6]].sum(axis=1)
r["HOLD"] = r[Y[6]]
key = ["anchor", "start", "len", "exit", "tp", "sl"]

print("Paired effect of filters (mean $ change vs. same setup unfiltered; % of pairs improved)")
base = r[(r.dir == "both") & (r.trend == "none") & (r.width == "all")].set_index(key)
for col, lvl in [("dir", "long"), ("dir", "short"), ("trend", "with"),
                 ("width", "skipwide"), ("width", "skipnarrow")]:
    f = r[(r[col] == lvl) & (r[[c for c in ["dir", "trend", "width"] if c != col]] ==
                              pd.Series({"dir": "both", "trend": "none", "width": "all"})
                              [[c for c in ["dir", "trend", "width"] if c != col]].values).all(axis=1)]
    f = f.set_index(key)
    j = f.join(base, rsuffix="_b", how="inner")
    out = []
    for p in ["IS", "VAL", "HOLD"] + Y:
        d = j[p] - j[p + "_b"]
        out.append(f"{p}: {d.mean():+7.0f} ({(d > 0).mean():.0%})")
    print(f"  {col}={lvl:10s} " + " | ".join(out[:3]) + "\n      by year: " + " ".join(out[3:]))

print("\nUnfiltered setups: mean $ by design choice (and % of setups profitable)")
b = r[(r.dir == "both") & (r.trend == "none") & (r.width == "all")].copy()
b["block"] = np.where(b.anchor == "NewYork", "NY", "LDN") + "_" + \
    pd.cut(np.where(b.anchor == "NewYork", b.start + 300, b.start),  # rough NY->London
           [0, 540, 840, 960, 2000], labels=["07-09", "09-14", "14-16", "16+"]).astype(str)
for col in ["block", "len", "tp", "sl", "exit"]:
    g = b.groupby(col)[["IS", "VAL", "HOLD"]]
    t = g.mean().round(0).join((g.agg(lambda s: (s > 0).mean()) * 100).round(0), rsuffix="_%pos")
    t["n"] = b.groupby(col).size()
    print(f"\n-- {col}\n{t.to_string()}")
