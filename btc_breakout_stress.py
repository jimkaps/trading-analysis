"""Stress test of the BTC 60-min Bollinger breakout from bb_breakout.py.

Core rules: 60-min bars (UTC), BB 20 / 3.0. First close outside the band -> trade with the break at
the next 1-min open. Stop starts at 1.5 x ATR14(60m) and trails up to the middle band; time exit after
50 bars. One position at a time. Fee 0.05% of position per round trip. $ on a fixed $50,000 position.

Checks
  1. Nearby settings: BB length 15/20/30, std 2.25-3.5, stop 1-3 ATR, time stop 25/50/100 bars,
     hourly bars shifted by 0/15/30/45 min.
  2. Costs 0.05 / 0.10 / 0.20 / 0.30 % round trip; entry 1 / 5 / 15 / 60 minutes late.
  3. Weekend gap: Dukascopy has no Saturday data, so trades held over it can't be stopped out on
     Saturday. Variant: go flat before every data gap.
  4. Random entries: same number of trades, same long/short mix, same exits, at random hourly closes.
  5. Walk-forward: each year from 2022, use the setting that did best over the previous two years.
  6. Trade-level: long vs short by year, quarterly results, profit concentration, drawdowns.

Usage: python btc_breakout_stress.py
"""
import itertools
import time

import numpy as np
import pandas as pd
from numba import njit

from bb_scalp import pick

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 300)

NOTIONAL = 50_000
FEE = 0.05
YEARS = list(range(2020, 2027))
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
CORE = dict(ln=20, k=3.0, off=0, sl=1.5, tb=50)


@njit(cache=True)
def sim(sig_pos, sig_dir, sig_atr, O, H, L, C, mid1m, sl_k, max_min, lim):
    """Breakout trade with stop trailing to the middle band. lim[s] = last index the trade may use."""
    n = len(O)
    m = len(sig_pos)
    ret = np.full(m, np.nan)
    xpos = np.full(m, -1, np.int64)
    for s in range(m):
        p = sig_pos[s] + 1
        if p >= n or not (sig_atr[s] > 0):
            continue
        d = sig_dir[s]
        e = O[p]
        stop = e - d * sl_k * sig_atr[s]
        end = min(p + max_min, n, lim[s] + 1)
        if end <= p:
            continue
        x = np.nan
        xj = end - 1
        for j in range(p, end):
            mm = mid1m[j - 1]
            if d > 0 and mm > stop:
                stop = mm
            elif d < 0 and mm < stop:
                stop = mm
            if d > 0 and L[j] <= stop:
                x = min(O[j], stop); xj = j; break
            if d < 0 and H[j] >= stop:
                x = max(O[j], stop); xj = j; break
        if np.isnan(x):
            x = C[end - 1]
        ret[s] = d * (x - e) / e * 100.0
        xpos[s] = xj
    return ret, xpos


class BTC:
    def __init__(self):
        df = pd.read_parquet("btc_1m.parquet")
        self.df, self.idx = df, df.index
        self.O, self.H, self.L, self.C = (df[c].to_numpy(float) for c in ("open", "high", "low", "close"))
        self.n = len(df)
        self.year = self.idx.year.to_numpy()
        gap = np.r_[np.diff(self.idx.values).astype("timedelta64[m]").astype(np.int64) > 1, True]
        g = np.where(gap)[0]                                  # last index before each gap
        self.next_gap = g[np.searchsorted(g, np.arange(self.n))]
        self.nolim = np.full(self.n, self.n, np.int64)
        self.cache = {}

    def bars(self, ln, off):
        key = (ln, off)
        if key not in self.cache:
            b = self.df.resample("60min", offset=f"{off}min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            end = np.searchsorted(self.idx.values, (b.index + pd.Timedelta(minutes=60)).values) - 1
            bc, bh, bl = b.close.to_numpy(), b.high.to_numpy(), b.low.to_numpy()
            pc = np.r_[np.nan, bc[:-1]]
            atr = pd.Series(np.nanmax(np.column_stack([bh - bl, np.abs(bh - pc), np.abs(bl - pc)]), axis=1)
                            ).rolling(14).mean().to_numpy()
            mid = b.close.rolling(ln).mean().to_numpy()
            sd = b.close.rolling(ln).std(ddof=0).to_numpy()
            m1 = np.full(self.n, np.nan); m1[end] = mid
            self.cache[key] = dict(end=end, bc=bc, atr=atr, mid=mid, sd=sd, mid1m=pd.Series(m1).ffill().to_numpy())
        return self.cache[key]

    def signals(self, ln, k, off):
        b = self.bars(ln, off)
        up, dn = b["mid"] + k * b["sd"], b["mid"] - k * b["sd"]
        bc = b["bc"]
        pbc = np.r_[np.nan, bc[:-1]]
        lg = (bc > up) & ~(pbc > np.r_[np.nan, up[:-1]])
        sh = (bc < dn) & ~(pbc < np.r_[np.nan, dn[:-1]])
        bi = np.r_[np.where(lg)[0], np.where(sh)[0]]
        dr = np.r_[np.ones(lg.sum()), -np.ones(sh.sum())]
        o = np.argsort(bi, kind="stable")
        bi, dr = bi[o], dr[o]
        return b["end"][bi].astype(np.int64), dr, b["atr"][bi], b

    def trades(self, ln=20, k=3.0, off=0, sl=1.5, tb=50, fee=FEE, delay=0, flat_gap=False):
        pos, dr, atr, b = self.signals(ln, k, off)
        p = pos + delay
        ok = p + 1 < self.n
        p, dr, atr = p[ok], dr[ok], atr[ok]
        lim = self.next_gap[np.minimum(p + 1, self.n - 1)] if flat_gap else self.nolim[:len(p)]
        ret, xpos = sim(p, dr, atr, self.O, self.H, self.L, self.C, b["mid1m"], sl, tb * 60, lim)
        tk = pick(p, xpos, ~np.isnan(ret))
        t = pd.DataFrame({"entry": self.idx[p[tk] + 1], "exit": self.idx[xpos[tk]], "dir": dr[tk],
                          "net": ret[tk] - fee, "hold_h": (xpos[tk] - p[tk]) / 60})
        return t


def summ(t):
    y = t.entry.dt.year
    out = {"trades/yr": len(t) / 6.87, "net%": t.net.mean(), "$/yr": t.net.sum() / 100 * NOTIONAL / 6.87}
    for p, ys in PERIODS.items():
        out[p] = t.net[y.isin(list(ys))].mean()
    out["yrs>0"] = int((t.groupby(y).net.sum() > 0).sum())
    eq = (t.net / 100 * NOTIONAL).cumsum()
    out["maxDD $"] = (eq.cummax() - eq).max()
    return out


def main():
    t0 = time.time()
    m = BTC()
    P = list(PERIODS)

    core = m.trades()
    print("===== Core: BB 20 / 3.0, stop 1.5 ATR -> middle band, 50-bar time stop, 0.05% fee =====")
    print(pd.Series(summ(core)).round(3).to_string())

    # 1. nearby settings
    rows = []
    for ln, k, off, sl, tb in itertools.product([15, 20, 30], [2.25, 2.5, 2.75, 3.0, 3.25, 3.5], [0, 15, 30, 45],
                                                [1.0, 1.5, 2.0, 3.0], [25, 50, 100]):
        rows.append({"len": ln, "std": k, "offset": off, "sl": sl, "tbars": tb, **summ(m.trades(ln, k, off, sl, tb))})
    nb = pd.DataFrame(rows)
    nb["ok"] = (nb[P] > 0).all(axis=1)
    nb.to_parquet("btc_breakout_nb.parquet")
    print(f"\n===== 1. Nearby settings: {len(nb)} variants [{time.time() - t0:.0f}s] =====")
    print(f"positive in every period: {nb.ok.mean():.0%}; positive overall: {(nb['net%'] > 0).mean():.0%}; "
          f"median net/trade {nb['net%'].median():.3f}%, median $/yr {nb['$/yr'].median():,.0f}, "
          f"median maxDD ${nb['maxDD $'].median():,.0f}")
    for dim in ["len", "std", "offset", "sl", "tbars"]:
        g = nb.groupby(dim)
        d = g[P + ["net%", "trades/yr", "maxDD $"]].median().round(3)
        d["% every period>0"] = (g.ok.mean() * 100).round(0)
        print(f"-- by {dim} --"); print(d.to_string())

    # 2. costs and late entry, 3. weekend gap
    rows = []
    for fee in [0.05, 0.10, 0.20, 0.30]:
        rows.append({"variant": f"fee {fee}%", **summ(m.trades(fee=fee))})
    for dl in [1, 5, 15, 60]:
        rows.append({"variant": f"entry {dl} min late", **summ(m.trades(delay=dl))})
    rows.append({"variant": "flat before data gaps", **summ(m.trades(flat_gap=True))})
    rows.append({"variant": "flat before gaps + fee 0.10%", **summ(m.trades(flat_gap=True, fee=0.10))})
    print("\n===== 2-3. Costs, late entry, weekend gap (core setting) =====")
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    # same across the neighbourhood at 0.20% fee
    nb20 = nb.copy()
    tr = nb20["trades/yr"]
    for p in P + ["net%"]:
        nb20[p] = nb20[p] - 0.15
    print(f"  all variants at 0.20% fee: positive in every period {(nb20[P] > 0).all(axis=1).mean():.0%}, "
          f"median net/trade {nb20['net%'].median():.3f}%")

    # 4. random entries
    pos, dr, atr, b = m.signals(20, 3.0, 0)
    end = b["end"]
    okb = ~np.isnan(b["atr"]) & ~np.isnan(b["mid"])
    cand = end[okb].astype(np.int64)
    catr = b["atr"][okb]
    lim = m.nolim[:len(cand)]
    rl, xl = sim(cand, np.ones(len(cand)), catr, m.O, m.H, m.L, m.C, b["mid1m"], 1.5, 3000, lim)
    rs, xs = sim(cand, -np.ones(len(cand)), catr, m.O, m.H, m.L, m.C, b["mid1m"], 1.5, 3000, lim)
    ns, nl = len(pos), int((dr > 0).sum())
    rng = np.random.default_rng(7)
    real = core.net.mean()
    real_l, real_s = core.net[core.dir > 0].mean(), core.net[core.dir < 0].mean()
    sims, sl_, ss_ = [], [], []
    for _ in range(2000):
        ch = np.sort(rng.choice(len(cand), ns, replace=False))
        d = np.where(rng.random(ns) < nl / ns, 1.0, -1.0)
        r = np.where(d > 0, rl[ch], rs[ch]); x = np.where(d > 0, xl[ch], xs[ch])
        tk = pick(cand[ch], x, ~np.isnan(r))
        rr = r[tk] - FEE; dd = d[tk]
        sims.append(rr.mean()); sl_.append(rr[dd > 0].mean()); ss_.append(rr[dd < 0].mean())
    sims, sl_, ss_ = map(np.array, (sims, sl_, ss_))
    print("\n===== 4. Random entries: same trade count, long/short mix and exits, 2,000 draws =====")
    print(pd.DataFrame({"breakout": [real, real_l, real_s],
                        "random median": [np.median(sims), np.median(sl_), np.median(ss_)],
                        "random 99th pct": [np.percentile(sims, 99), np.percentile(sl_, 99), np.percentile(ss_, 99)],
                        "p (random >= breakout)": [(sims >= real).mean(), (sl_ >= real_l).mean(), (ss_ >= real_s).mean()]},
                       index=["all", "longs", "shorts"]).round(4).to_string())

    # 5. walk-forward
    grid = list(itertools.product([2.0, 2.5, 3.0, 3.5], [1.0, 1.5, 2.0, 3.0], [25, 50, 100]))
    yearly = {}
    for k, sl, tb in grid:
        t = m.trades(20, k, 0, sl, tb)
        yearly[(k, sl, tb)] = t.groupby(t.entry.dt.year).net.agg(["sum", "count"])
    rows = []
    for Y in range(2022, 2027):
        train = {g: v["sum"].reindex([Y - 2, Y - 1]).fillna(0).sum() for g, v in yearly.items()}
        best = max(train, key=train.get)
        test = yearly[best].reindex([Y]).fillna(0)
        allY = pd.Series({g: v["sum"].get(Y, 0) / max(v["count"].get(Y, 1), 1) for g, v in yearly.items()})
        rows.append({"year": Y, "chosen (std, sl, bars)": best, "trades": int(test["count"].iloc[0]),
                     "net %/trade": test["sum"].iloc[0] / max(test["count"].iloc[0], 1),
                     "$ on 50k": test["sum"].iloc[0] / 100 * NOTIONAL,
                     "median of all 48 settings %/trade": allY.median(),
                     "% of settings >0 that year": (allY > 0).mean() * 100})
    print("\n===== 5. Walk-forward (pick best of 48 settings on the prior 2 years, trade the next year) =====")
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    # 6. trade-level
    t = core.copy()
    t["year"] = t.entry.dt.year
    print("\n===== 6. Core trades: by year and side (net % per trade, $ on 50k) =====")
    g = t.groupby(["year"])
    yt = pd.DataFrame({"trades": g.size(), "net %": g.net.mean(), "$": g.net.sum() / 100 * NOTIONAL,
                       "win %": g.net.apply(lambda x: (x > 0).mean() * 100),
                       "long %/trade": t[t.dir > 0].groupby("year").net.mean(),
                       "short %/trade": t[t.dir < 0].groupby("year").net.mean(),
                       "avg hold h": g.hold_h.mean()})
    print(yt.round(3).to_string())
    q = t.groupby(t.entry.dt.to_period("Q")).net.sum() / 100 * NOTIONAL
    print(f"\nquarters positive: {(q > 0).sum()} of {len(q)}; worst quarter ${q.min():,.0f}; best ${q.max():,.0f}")
    srt = t.net.sort_values(ascending=False)
    tot = t.net.sum()
    for frac in (0.01, 0.05, 0.10):
        k = int(len(t) * frac)
        print(f"top {frac:.0%} of trades ({k}) = {srt.iloc[:k].sum() / tot:.0%} of profit; "
              f"without them net/trade = {srt.iloc[k:].mean():.3f}%")
    eq = (t.set_index("exit").net / 100 * NOTIONAL).cumsum()
    dd = eq.cummax() - eq
    under = dd > 0
    runs, start = [], None
    for ts, u in under.items():
        if u and start is None:
            start = ts
        elif not u and start is not None:
            runs.append((ts - start).days); start = None
    if start is not None:
        runs.append((eq.index[-1] - start).days)
    roll = eq.resample("D").last().ffill()
    worst12 = (roll - roll.shift(365)).min()
    print(f"max drawdown ${dd.max():,.0f}; longest time below a previous high {max(runs)} days; "
          f"worst 12-month result ${worst12:,.0f}")
    streak = (t.net < 0).astype(int)
    print(f"longest losing streak: {streak.groupby((streak == 0).cumsum()).sum().max()} trades; "
          f"win rate {(t.net > 0).mean():.0%}; avg win {t.net[t.net > 0].mean():.3f}% vs avg loss {t.net[t.net < 0].mean():.3f}%")
    print(f"[{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
