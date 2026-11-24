"""Out-of-sample test of the BTC 60-min Bollinger breakout on 2017-2019 (never used in its design).

Same rules and code as btc_breakout_stress.py (BB 20 / 3.0 on 60-min bars, first close outside the band,
trade with the break at the next 1-min open, stop 1.5 x ATR14 trailing to the middle band, 50-bar time
stop, 0.05% fee round trip, $50,000 position), run on 2017-2026 data with 2017-19 reported separately.

Checks on 2017-19: core by year and side; 864 nearby settings; fees and late entry; flat before data
gaps; random entries (same count, long/short mix and exits, 2,000 draws).

Usage: python btc_oos_test.py btc_1m_2017_2026.parquet
"""
import itertools
import sys

import numpy as np
import pandas as pd

import btc_breakout_stress as b
from bb_scalp import pick

NOTIONAL, FEE = 50_000, 0.05
PERIODS = {"2017-19 (never seen)": range(2017, 2020), "2020-23": range(2020, 2024),
           "2024-25": range(2024, 2026), "2026": [2026]}
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)


class BTCFile(b.BTC):
    def __init__(self, path):
        df = pd.read_parquet(path)
        self.df, self.idx = df, df.index
        self.O, self.H, self.L, self.C = (df[c].to_numpy(float) for c in ("open", "high", "low", "close"))
        self.n = len(df)
        self.year = self.idx.year.to_numpy()
        gap = np.r_[np.diff(self.idx.values).astype("timedelta64[m]").astype(np.int64) > 1, True]
        g = np.where(gap)[0]
        self.next_gap = g[np.searchsorted(g, np.arange(self.n))]
        self.nolim = np.full(self.n, self.n, np.int64)
        self.cache = {}


def summ(t):
    y = t.entry.dt.year
    out = {}
    for p, ys in PERIODS.items():
        x = t.net[y.isin(list(ys))]
        out[f"{p} %/trade"] = x.mean()
        out[f"{p} trades/yr"] = len(x) / len(list(ys))
    old = t[y < 2020]
    eq = (old.net / 100 * NOTIONAL).cumsum()
    out["2017-19 $/yr"] = old.net.sum() / 100 * NOTIONAL / 3
    out["2017-19 maxDD $"] = (eq.cummax() - eq).max() if len(eq) else np.nan
    out["2017-19 yrs>0"] = int((old.groupby(old.entry.dt.year).net.sum() > 0).sum())
    return out


def main():
    m = BTCFile(sys.argv[1] if len(sys.argv) > 1 else "btc_1m_2017_2026.parquet")
    print(f"Data: {m.idx[0]} -> {m.idx[-1]}, {m.n:,} 1-min bars")
    core = m.trades()
    print("\n===== Core rule =====")
    print(pd.Series(summ(core)).round(3).to_string())

    t = core.copy(); t["year"] = t.entry.dt.year
    g = t.groupby("year")
    print("\nBy year:")
    print(pd.DataFrame({"trades": g.size(), "net %/trade": g.net.mean(), "$ on 50k": g.net.sum() / 100 * NOTIONAL,
                        "win %": g.net.apply(lambda x: (x > 0).mean() * 100),
                        "long %/trade": t[t.dir > 0].groupby("year").net.mean(),
                        "short %/trade": t[t.dir < 0].groupby("year").net.mean()}).round(3).to_string())

    # nearby settings
    rows = []
    for ln, k, off, sl, tb in itertools.product([15, 20, 30], [2.5, 2.75, 3.0, 3.25], [0, 15, 30, 45],
                                                [1.0, 1.5, 2.0], [25, 50, 100]):
        tt = m.trades(ln, k, off, sl, tb)
        old = tt[tt.entry.dt.year < 2020]
        yr = old.groupby(old.entry.dt.year).net.sum()
        rows.append({"len": ln, "std": k, "off": off, "sl": sl, "tb": tb, "old %/trade": old.net.mean(),
                     "old yrs>0": int((yr > 0).sum()),
                     "new %/trade": tt.net[tt.entry.dt.year >= 2020].mean()})
    nb = pd.DataFrame(rows)
    print(f"\n===== Nearby settings ({len(nb)}): 2017-19 =====")
    print(f"made money in 2017-19: {(nb['old %/trade'] > 0).mean():.0%}; in all 3 years: {(nb['old yrs>0'] == 3).mean():.0%}; "
          f"median {nb['old %/trade'].median():.3f}%/trade (2020-26 median {nb['new %/trade'].median():.3f}%)")
    for dim in ["std", "sl", "tb", "off"]:
        print(f"-- by {dim} --")
        print(nb.groupby(dim)[["old %/trade", "new %/trade"]].median().round(3).to_string())

    # costs, late entry, gaps
    rows = []
    for lab, kw in [("fee 0.05%", {}), ("fee 0.10%", dict(fee=0.10)), ("fee 0.20%", dict(fee=0.20)),
                    ("entry 5 min late", dict(delay=5)), ("entry 15 min late", dict(delay=15)),
                    ("flat before data gaps", dict(flat_gap=True))]:
        tt = m.trades(**kw)
        old = tt[tt.entry.dt.year < 2020]
        rows.append({"variant": lab, "2017-19 %/trade": old.net.mean(),
                     "2017-19 $/yr": old.net.sum() / 100 * NOTIONAL / 3,
                     "2020-26 %/trade": tt.net[tt.entry.dt.year >= 2020].mean()})
    print("\n===== Costs, late entry, weekend gaps =====")
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    # random entries, 2017-19 only
    pos, dr, atr, bb = m.signals(20, 3.0, 0)
    end = bb["end"]
    okb = ~np.isnan(bb["atr"]) & ~np.isnan(bb["mid"]) & (m.idx[np.minimum(end, m.n - 1)].year < 2020)
    cand = end[okb].astype(np.int64); catr = bb["atr"][okb]
    lim = m.nolim[:len(cand)]
    rl, xl = b.sim(cand, np.ones(len(cand)), catr, m.O, m.H, m.L, m.C, bb["mid1m"], 1.5, 3000, lim)
    rs, xs = b.sim(cand, -np.ones(len(cand)), catr, m.O, m.H, m.L, m.C, bb["mid1m"], 1.5, 3000, lim)
    old = core[core.entry.dt.year < 2020]
    ns, nl = len(old), int((old.dir > 0).sum())
    rng = np.random.default_rng(7)
    sims, sl_, ss_ = [], [], []
    for _ in range(2000):
        ch = np.sort(rng.choice(len(cand), ns, replace=False))
        d = np.where(rng.random(ns) < nl / ns, 1.0, -1.0)
        r = np.where(d > 0, rl[ch], rs[ch]); x = np.where(d > 0, xl[ch], xs[ch])
        tk = pick(cand[ch], x, ~np.isnan(r))
        rr = r[tk] - FEE; dd = d[tk]
        sims.append(rr.mean()); sl_.append(rr[dd > 0].mean()); ss_.append(rr[dd < 0].mean())
    sims, sl_, ss_ = map(np.array, (sims, sl_, ss_))
    real, rlg, rsh = old.net.mean(), old.net[old.dir > 0].mean(), old.net[old.dir < 0].mean()
    print(f"\n===== Random entries, 2017-19 ({ns} trades, 2,000 draws) =====")
    print(pd.DataFrame({"breakout": [real, rlg, rsh],
                        "random median": [np.median(sims), np.median(sl_), np.median(ss_)],
                        "random 95th pct": [np.percentile(sims, 95), np.percentile(sl_, 95), np.percentile(ss_, 95)],
                        "p (random >= breakout)": [(sims >= real).mean(), (sl_ >= rlg).mean(), (ss_ >= rsh).mean()]},
                       index=["all", "longs", "shorts"]).round(4).to_string())


if __name__ == "__main__":
    main()
