"""Score regions of parameter space built from the robust effects, plus pick within each on 2020-2023 only."""
import sys

import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
r = pd.read_parquet(sys.argv[1])
for c in ["anchor", "tp", "sl", "dir", "trend", "width"]:
    r[c] = r[c].astype(str)
Y = [f"y{y}" for y in range(2020, 2027)]
r["IS"] = r[Y[:4]].sum(axis=1)
r["VAL"] = r[Y[4:6]].sum(axis=1)
r["HOLD"] = r[Y[6]]
r["total"] = r[Y].sum(axis=1)
r["posyrs"] = (r[Y] > 0).sum(axis=1)
r["winrate"] = r.wins / r.trades


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


regions = {
    "US open, London clock": dict(anchor="London", start=[855, 870, 885, 900, 915], len=[45, 60, 90],
                                  exit=[1255], tp=["1.5%", "2.0%", "none"], sl=["0.5%", "0.75%", "1.0%"]),
    "US open, NY clock": dict(anchor="NewYork", start=[555, 570, 585, 600, 615], len=[45, 60, 90],
                              exit=[955], tp=["1.5%", "2.0%", "none"], sl=["0.5%", "0.75%", "1.0%"]),
    "Your morning window": dict(anchor="London", start=[420, 435, 450, 465, 480], len=[45, 60, 90],
                                exit=[1170, 1255], tp=["1.5%", "2.0%", "none"], sl=["0.35%", "0.5%", "0.75%"]),
}
cols = ["range", "ex", "tp", "sl", "width", "trades", "winrate", "maxdd", "IS", "VAL", "HOLD", "total", "posyrs"] + Y
for name, g in regions.items():
    q = r[(r.anchor == g["anchor"]) & r.start.isin(g["start"]) & r.len.isin(g["len"]) & r.exit.isin(g["exit"])
          & r.tp.isin(g["tp"]) & r.sl.isin(g["sl"]) & (r.dir == "both") & (r.trend == "none")]
    print(f"\n===== {name} =====")
    for w in ["all", "skipwide"]:
        s = q[q.width == w]
        print(f"  width={w:8s} n={len(s):3d}  median: IS ${s.IS.median():7,.0f}  VAL ${s.VAL.median():7,.0f}  "
              f"HOLD ${s.HOLD.median():7,.0f}  | %>0: IS {(s.IS > 0).mean():.0%} VAL {(s.VAL > 0).mean():.0%} "
              f"HOLD {(s.HOLD > 0).mean():.0%} | median maxDD ${s.maxdd.median():,.0f}")
    s = q[q.width == "skipwide"].sort_values("IS", ascending=False).head(5)
    s = s.assign(range=s.start.map(hhmm) + "+" + s.len.astype(str), ex=s.exit.map(hhmm))
    print("  Best 5 by 2020-2023 only (skipwide):")
    print(s[cols].round(2).to_string(index=False))
