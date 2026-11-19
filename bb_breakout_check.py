"""Checks on the 60-min Bollinger breakout results from bb_breakout.py.

1. 60-min settings only: median net per period and share positive in every period, per market/filter.
2. Settings positive in every period on 3-4 markets, by year.
3. Drift control: BTC rose ~10x and NQ ~2.5x in 2020-26, so a long-biased trend system profits
   from the rise alone. Each breakout's longs and shorts are compared with RANDOM entries
   (every 60-min bar close, long-only and short-only) using the same exit, stop and costs.
   Edge = breakout average - random average, per side.

Usage: python bb_breakout_check.py   (needs bb_breakout_results.parquet)
"""
import itertools

import numpy as np
import pandas as pd

from bb_breakout import MARKETS, EXITS, SLS, PERIODS, YEARS, TIME_BARS, BB_LEN, sim_trend, resample, add_periods

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 300)
P = list(PERIODS)


def main():
    res = add_periods(pd.read_parquet("bb_breakout_results.parquet"))
    h = res[res.tf == 60]
    print("===== 60-min breakouts only: median net % per trade over 48 settings (3 std x 4 exits x 4 stops) =====")
    g = h.groupby(["market", "filter"], sort=False)
    print(pd.DataFrame({"trades/yr": (g.trades.median() / 6.87).round(0),
                        **{f"med {p}": g[p].median().round(4) for p in P},
                        "med long": g["net long"].median().round(4), "med short": g["net short"].median().round(4),
                        "% every period>0": (g.ok.mean() * 100).round(0)}).to_string())

    key = ["tf", "std", "exit", "sl", "filter"]
    cnt = h.groupby(key).ok.sum()
    print("\n60-min settings positive in every period, by number of markets:")
    print(cnt.value_counts().sort_index().to_string())
    best = cnt[cnt >= 3].index
    sub = h.set_index(key).loc[best].reset_index()
    cols = key + ["market", "trades", "net", "net long", "net short"] + [f"s{y}" for y in YEARS]
    sub = sub.copy()
    for y in YEARS:
        sub[f"s{y}"] = sub[f"s{y}"] / sub[f"n{y}"].clip(lower=1)
    print("\nSettings positive every period on >= 3 markets (yearly columns = avg net % per trade):")
    print(sub[cols].sort_values(key + ["market"]).round(3).to_string(index=False))

    print("\n===== Drift control: breakout vs random 60-min entries with the same exits (no filter, net %/trade) =====")
    rows = []
    for name, (path, drop, ckind, cval) in MARKETS.items():
        df = pd.read_parquet(path)
        if drop:
            df = df[~((df.volume == 0) & (df.high == df.low))]
        idx = df.index
        O, H, L, C = (df[c].to_numpy(float) for c in ("open", "high", "low", "close"))
        n = len(df)
        b, end = resample(df, idx, 60)
        bc, bh, bl = b.close.to_numpy(), b.high.to_numpy(), b.low.to_numpy()
        pc = np.r_[np.nan, bc[:-1]]
        atr = pd.Series(np.nanmax(np.column_stack([bh - bl, np.abs(bh - pc), np.abs(bl - pc)]), axis=1)
                        ).rolling(14).mean().to_numpy()
        mid = b.close.rolling(BB_LEN).mean().to_numpy()
        mid1m = np.full(n, np.nan); mid1m[end] = mid
        mid1m = pd.Series(mid1m).ffill().to_numpy()
        ok = ~np.isnan(atr) & ~np.isnan(mid)
        pos = end[ok].astype(np.int64)
        a = atr[ok]
        ent = O[np.minimum(pos + 1, n - 1)]
        cost = np.full(len(pos), cval) if ckind == "pct" else cval / ent * 100
        yrs = idx.year.to_numpy()[pos]
        for (ex, mode, tp_r), slk in itertools.product(EXITS, SLS):
            base = {}
            for side, d in (("long", 1.0), ("short", -1.0)):
                r, _ = sim_trend(pos, np.full(len(pos), d), a, O, H, L, C, mid1m, slk, mode, tp_r, TIME_BARS * 60)
                r = r - cost
                base[side] = np.nanmean(r)
                base[side + " 24-26"] = np.nanmean(r[yrs >= 2024])
            for k in (2.0, 2.5, 3.0):
                q = h[(h.market == name) & (h["std"] == k) & (h.exit == ex) & (h.sl == slk) & (h["filter"] == "(none)")]
                if q.empty:
                    continue
                q = q.iloc[0]
                rows.append({"market": name, "std": k, "exit": ex, "sl": slk,
                             "brk long": q["net long"], "rand long": base["long"],
                             "brk short": q["net short"], "rand short": base["short"],
                             "edge long": q["net long"] - base["long"], "edge short": q["net short"] - base["short"]})
    d = pd.DataFrame(rows)
    gm = d.groupby("market")
    print(pd.DataFrame({"med brk long": gm["brk long"].median(), "med rand long": gm["rand long"].median(),
                        "med edge long": gm["edge long"].median(),
                        "med brk short": gm["brk short"].median(), "med rand short": gm["rand short"].median(),
                        "med edge short": gm["edge short"].median(),
                        "% settings edge>0 both sides": gm.apply(
                            lambda x: ((x["edge long"] > 0) & (x["edge short"] > 0)).mean() * 100)}).round(4).to_string())
    print("\nBy exit (median over markets x std x stop):")
    print(d.groupby("exit")[["edge long", "edge short"]].median().round(4).to_string())
    d.to_parquet("bb_breakout_drift.parquet")


if __name__ == "__main__":
    main()
