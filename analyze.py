"""Rank sweep results: select on 2020-2023, validate on 2024-2025, hold out 2026.

Usage: python analyze.py results.parquet
"""
import sys

import numpy as np
import pandas as pd

TP_ORDER = ["0.3%", "0.5%", "0.75%", "1.0%", "1.25%", "1.5%", "2.0%", "none", "1R", "2R", "3R"]
SL_ORDER = ["0.25%", "0.35%", "0.5%", "0.75%", "1.0%", "range"]
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def main():
    r = pd.read_parquet(sys.argv[1])
    for c in ["anchor", "tp", "sl", "dir", "trend", "width"]:
        r[c] = r[c].astype(str)
    r["IS"] = r[["y2020", "y2021", "y2022", "y2023"]].sum(axis=1)
    r["VAL"] = r[["y2024", "y2025"]].sum(axis=1)
    r["HOLD"] = r["y2026"]
    r["IS_posyears"] = (r[["y2020", "y2021", "y2022", "y2023"]] > 0).sum(axis=1)
    r["winrate"] = r["wins"] / r["trades"].clip(lower=1)
    r["tpi"] = r["tp"].map({v: i for i, v in enumerate(TP_ORDER)})
    r["sli"] = r["sl"].map({v: i for i, v in enumerate(SL_ORDER)})
    r = r[r["trades"] >= 250].copy()
    print(f"{len(r):,} variants with >= 250 trades")

    # ---- Neighbourhood smoothing of the in-sample score ----
    # neighbours: start +-15, len next/prev, tp next/prev (pct family), sl next/prev
    keys = ["anchor", "exit", "dir", "trend", "width"]
    idx = r.set_index(keys + ["start", "len", "tpi", "sli"])["IS"]
    lens = sorted(r["len"].unique())
    li = {v: i for i, v in enumerate(lens)}
    base = r[keys + ["start", "len", "tpi", "sli"]].to_numpy(dtype=object)
    shifts = []
    for ds in (-15, 0, 15):
        for dl in (-1, 0, 1):
            for dt in (-1, 0, 1):
                for dsl in (-1, 0, 1):
                    if (ds, dl, dt, dsl) != (0, 0, 0, 0) and abs(ds // 15) + abs(dl) + abs(dt) + abs(dsl) <= 2:
                        shifts.append((ds, dl, dt, dsl))
    vals = [r["IS"].to_numpy()]
    for ds, dl, dt, dsl in shifts:
        nl = [lens[li[l] + dl] if 0 <= li[l] + dl < len(lens) else -1 for l in r["len"]]
        k = pd.MultiIndex.from_arrays([r[c] for c in keys] + [r["start"] + ds, nl,
                                       r["tpi"] + dt, r["sli"] + dsl])
        vals.append(idx.reindex(k).to_numpy())
    V = np.vstack(vals)
    r["IS_nbr"] = np.nanmean(V, axis=0)
    r["nbr_pos"] = np.nanmean(V > 0, axis=0)

    # ---- Selection-bias check ----
    for col in ["IS", "IS_nbr"]:
        top = r.sort_values(col, ascending=False).head(200)
        print(f"\nTop 200 by {col}: VAL>0 in {(top.VAL > 0).mean():.0%}, median VAL ${top.VAL.median():,.0f}, "
              f"HOLD>0 in {(top.HOLD > 0).mean():.0%}, median HOLD ${top.HOLD.median():,.0f}")
    print(f"All variants: VAL>0 in {(r.VAL > 0).mean():.0%}, HOLD>0 in {(r.HOLD > 0).mean():.0%}")

    # ---- Candidate list: smoothed IS, all four IS years positive, neighbours mostly positive ----
    cand = r[(r.IS_posyears >= 3) & (r.nbr_pos >= 0.8)].sort_values("IS_nbr", ascending=False)
    # one per distinct idea (anchor/start/len/exit/filters) to avoid near-duplicates
    cand = cand.drop_duplicates(["anchor", "start", "len", "exit", "dir", "trend", "width"]).head(25)
    show = cand.assign(range=lambda d: d.start.map(hhmm) + "+" + d.len.astype(str),
                       ex=lambda d: d.exit.map(hhmm))
    cols = ["anchor", "range", "ex", "tp", "sl", "dir", "trend", "width", "trades", "winrate",
            "maxdd", "IS", "IS_nbr", "VAL", "HOLD"] + [f"y{y}" for y in range(2020, 2027)]
    print("\nTop candidates (selected on 2020-2023 only):")
    print(show[cols].round(2).to_string(index=False))

    # ---- Reference rows ----
    def ref(anchor, start, ln, ex, tp, sl, d="both", t="none", w="all"):
        q = r[(r.anchor == anchor) & (r.start == start) & (r.len == ln) & (r.exit == ex) & (r.tp == tp)
              & (r.sl == sl) & (r.dir == d) & (r.trend == t) & (r.width == w)]
        return q
    refs = pd.concat([
        ref("London", 450, 45, 960, "0.75%", "0.75%"),   # ~A (07:30-08:15, ~205pt, 16:00)
        ref("London", 450, 45, 1255, "1.5%", "0.5%"),    # ~B
        ref("London", 900, 30, 1110, "1.0%", "1.0%"),    # C
        ref("NewYork", 570, 30, 810, "1.0%", "1.0%"),    # C anchored to NY open
    ])
    print("\nReference setups (A~, B~, C, C in NY time):")
    print(refs.assign(range=lambda d: d.start.map(hhmm) + "+" + d.len.astype(str),
                      ex=lambda d: d.exit.map(hhmm))[cols].round(2).to_string(index=False))
    cand.to_csv("candidates.csv", index=False)


if __name__ == "__main__":
    main()
