"""Stress test of the one lead from bb_scalp.py:
15-min close outside the 2.5-3 sigma Bollinger Band, signal bar tests the daily VWAP, fade it.

Checks
  1. Nearby settings: BB length 15/20/30, std 2.25-3.0, VWAP tolerance 0.15/0.25/0.4 ATR,
     exit mid / 1R / 1.5R, stop 1.5/2/2.5 ATR, time stop 10/20/40 bars, and 15-min bars
     shifted by 0/5/10 minutes. Each one is compared with the same setting without the filter.
  2. Placebo: random filters that keep the same number of signals. How often does a random
     subset do as well as the VWAP subset?
  3. Core setting per year, long vs short, entry 0/1/2 minutes late.
  4. The same rules on NQ, ES and gold (closed-market filler bars dropped).
All figures are gross % of position per trade (before fees).

Usage: python bb_vwap_check.py
"""
import itertools
import time

import numpy as np
import pandas as pd

from bb_scalp import simulate, pick

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

YEARS = list(range(2020, 2027))
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
LENS = [15, 20, 30]
STDS = [2.25, 2.5, 2.75, 3.0]
TOLS = [0.15, 0.25, 0.4]
EXITS = [("mid", 0.0), ("1R", 1.0), ("1.5R", 1.5)]
SLS = [1.5, 2.0, 2.5]
TBARS = [10, 20, 40]
OFFSETS = [0, 5, 10]
TF = 15


def load(path, drop_filler):
    df = pd.read_parquet(path)
    if "volume" not in df:
        df["volume"] = 0.0
    if drop_filler:
        df = df[~((df.volume == 0) & (df.high == df.low))]
    return df


class Market:
    def __init__(self, df):
        self.df = df
        self.idx = df.index
        self.O, self.H, self.L, self.C, V = (df[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume"))
        self.n = len(df)
        self.year = self.idx.year.to_numpy()
        dcode, _ = pd.factorize(self.idx.floor("D"))
        tp = (self.H + self.L + self.C) / 3
        w = V + 1e-9
        self.vwap = (pd.Series(tp * w).groupby(dcode).cumsum() / pd.Series(w).groupby(dcode).cumsum()).to_numpy()
        self.bars = {}

    def tf_bars(self, offset):
        if offset not in self.bars:
            b = self.df.resample(f"{TF}min", label="left", closed="left", offset=f"{offset}min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            end = np.searchsorted(self.idx.values, (b.index + pd.Timedelta(minutes=TF)).values) - 1
            bc = b.close.to_numpy(); bh = b.high.to_numpy(); bl = b.low.to_numpy()
            prevc = np.r_[np.nan, bc[:-1]]
            trr = np.nanmax(np.column_stack([bh - bl, np.abs(bh - prevc), np.abs(bl - prevc)]), axis=1)
            atr = pd.Series(trr).rolling(14).mean().to_numpy()
            self.bars[offset] = (b, end, bc, bh, bl, atr, {})
        return self.bars[offset]

    def signals(self, offset, ln, k):
        b, end, bc, bh, bl, atr, cache = self.tf_bars(offset)
        if (ln, k) not in cache:
            mid = b.close.rolling(ln).mean().to_numpy()
            sd = b.close.rolling(ln).std(ddof=0).to_numpy()
            lg = bc < mid - k * sd; sh = bc > mid + k * sd
            bi = np.r_[np.where(lg)[0], np.where(sh)[0]]
            dr = np.r_[np.ones(lg.sum()), -np.ones(sh.sum())]
            o = np.argsort(bi, kind="stable"); bi, dr = bi[o], dr[o]
            mid1m = np.full(self.n, np.nan); mid1m[end] = mid
            mid1m = pd.Series(mid1m).ffill().to_numpy()
            pos = end[bi].astype(np.int64)
            vw = self.vwap[pos]
            cache[(ln, k)] = dict(pos=pos, dr=dr, lo=bl[bi], hi=bh[bi], cl=bc[bi], atr=atr[bi], vw=vw, mid1m=mid1m)
        return cache[(ln, k)]

    def vwap_mask(self, s, tol):
        t = tol * s["atr"]
        lg = (s["lo"] <= s["vw"] + t) & (s["cl"] >= s["vw"] - t)
        sh = (s["hi"] >= s["vw"] - t) & (s["cl"] <= s["vw"] + t)
        return np.where(s["dr"] > 0, lg, sh)

    def run(self, s, tp_r, slk, tbars, delay=0):
        return simulate(s["pos"] + delay, s["dr"], s["atr"], self.O, self.H, self.L, self.C, s["mid1m"],
                        slk, tp_r, tbars * TF)


def period_stats(r, y):
    out = {"trades": len(r), "avg all": r.mean() if len(r) else np.nan}
    for p, ys in PERIODS.items():
        sel = np.isin(y, list(ys))
        out[p] = r[sel].mean() if sel.any() else np.nan
        out[f"n {p}"] = int(sel.sum())
    out["yrs>0"] = sum((r[y == yy].mean() > 0) for yy in YEARS if (y == yy).any())
    return out


def neighbourhood(m):
    rows = []
    for off, ln, k in itertools.product(OFFSETS, LENS, STDS):
        s = m.signals(off, ln, k)
        masks = {tol: m.vwap_mask(s, tol) for tol in TOLS}
        allm = np.ones(len(s["pos"]), bool)
        yrs = m.year[s["pos"]]
        for (ex, tp_r), slk, tb in itertools.product(EXITS, SLS, TBARS):
            ret, xpos = m.run(s, tp_r, slk, tb)
            tk = pick(s["pos"], xpos, allm)
            base = period_stats(ret[tk], yrs[tk])
            for tol, mk in masks.items():
                tk = pick(s["pos"], xpos, mk)
                st = period_stats(ret[tk], yrs[tk])
                rows.append({"offset": off, "len": ln, "std": k, "tol": tol, "exit": ex, "sl": slk, "tbars": tb,
                             **st, **{f"base {p}": base[p] for p in PERIODS}, "base all": base["avg all"]})
    return pd.DataFrame(rows)


def summarize_nb(r, label, verbose=False):
    print(f"\n===== {label}: {len(r)} nearby settings, gross % per trade =====")
    t = {}
    for p in list(PERIODS) + ["all"]:
        col = p if p != "all" else "avg all"
        b = f"base {p}" if p != "all" else "base all"
        t[p] = {"median (VWAP)": r[col].median(), "median (no filter)": r[b].median(),
                "% settings > 0": (r[col] > 0).mean() * 100, "% > 0.05": (r[col] > 0.05).mean() * 100,
                "% > 0.10": (r[col] > 0.10).mean() * 100, "% beat no-filter": (r[col] > r[b]).mean() * 100}
    print(pd.DataFrame(t).round(3).to_string())
    print(f"median trades/yr {r.trades.median() / 6.87:.0f}; positive in all 3 periods: "
          f"{(r[list(PERIODS)] > 0).all(axis=1).mean():.0%}; >0.05 in all 3: {(r[list(PERIODS)] > 0.05).all(axis=1).mean():.0%}")
    for dim in ["offset", "len", "std", "tol", "exit", "sl", "tbars"] if verbose else ["std"]:
        g = r.groupby(dim)[list(PERIODS)].median().round(3)
        g["% all3>0"] = r.groupby(dim).apply(lambda x: (x[list(PERIODS)] > 0).all(axis=1).mean() * 100).round(0)
        print(f"-- by {dim}: median gross % --"); print(g.to_string())


def placebo(m, draws=2000, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for k, (ex, tp_r) in itertools.product([2.5, 2.75, 3.0], EXITS):
        s = m.signals(0, 20, k)
        mk = m.vwap_mask(s, 0.25)
        ret, xpos = m.run(s, tp_r, 2.0, 20)
        tk = pick(s["pos"], xpos, mk)
        real = ret[tk].mean()
        nsig = mk.sum(); N = len(mk)
        sims = np.empty(draws)
        for i in range(draws):
            rm = np.zeros(N, bool); rm[rng.choice(N, nsig, replace=False)] = True
            sims[i] = ret[pick(s["pos"], xpos, rm)].mean()
        rows.append({"std": k, "exit": ex, "VWAP avg": real, "random median": np.median(sims),
                     "random 95th pct": np.percentile(sims, 95), "p (random >= VWAP)": (sims >= real).mean(),
                     "trades": tk.sum()})
    return pd.DataFrame(rows)


def core_detail(m):
    s = m.signals(0, 20, 2.5)
    mk = m.vwap_mask(s, 0.25)
    yrs = m.year[s["pos"]]
    rows = []
    for (ex, tp_r) in EXITS:
        for delay in (0, 1, 2):
            ret, xpos = m.run(s, tp_r, 2.0, 20, delay)
            tk = pick(s["pos"], xpos, mk)
            for side, sm in [("both", np.ones(len(mk), bool)), ("long", s["dr"] > 0), ("short", s["dr"] < 0)]:
                if side != "both" and delay:
                    continue
                t = tk & sm
                r, y = ret[t], yrs[t]
                rec = {"exit": ex, "delay min": delay, "side": side, "trades": len(r), "avg": r.mean(),
                       "win%": (r > 0).mean() * 100}
                for yy in YEARS:
                    rec[yy] = r[y == yy].mean()
                rows.append(rec)
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    btc = Market(load("btc_1m.parquet", False))
    nb = neighbourhood(btc)
    nb.to_parquet("bb_vwap_nb_btc.parquet")
    summarize_nb(nb, "BTC", verbose=True)
    print(f"[{time.time() - t0:.0f}s]")

    print("\n===== Placebo: random filters keeping the same number of signals (len 20, tol 0.25, SL 2 ATR, 20 bars) =====")
    print(placebo(btc).round(4).to_string(index=False))

    print("\n===== Core: 15m, BB 20 / 2.5, tol 0.25, SL 2 ATR, 20 bars: avg gross % by year =====")
    print(core_detail(btc).round(3).to_string(index=False))
    print(f"[{time.time() - t0:.0f}s]")

    btc2 = Market(load("btc_1m.parquet", True))
    summarize_nb(neighbourhood(btc2), "BTC, flat zero-volume bars removed")

    for name, path in [("NQ", "nq_1m_vol.parquet"), ("ES", "es_1m.parquet"), ("Gold", "gold_1m.parquet")]:
        mk = Market(load(path, True))
        r = neighbourhood(mk)
        r.to_parquet(f"bb_vwap_nb_{name.lower()}.parquet")
        summarize_nb(r, name)
        print(f"[{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
