"""Stress test of the NQ cluster from bb_scalp.py:
15-min bar touches the 3 sigma Bollinger Band and closes back inside ("reject"), fade it,
1.5R target, 2 x ATR stop, with either the EMA200 filter or "any level + with 60m trend".

Checks (all net of costs as % of entry price: MNQ 1 pt slippage + $1.24 per round trip;
for ES, MES 0.5 pt + $1.24)
  1. Nearby and wider settings: BB length 15/20/30, std 2.75-3.5 (beyond the original 3.0 edge),
     level tolerance 0.15/0.25/0.4 ATR, target 1R/1.5R/2R, stop 1.5-3 ATR, time stop 10/20/40 bars,
     15-min bars shifted by 0/5/10 minutes. Each filter is compared with no filter.
  2. Placebo: random filters keeping the same number of signals.
  3. Core setting per year, long vs short, entry 0/1/2 minutes late, double slippage.
  4. The same rules on ES.

Usage: python bb_nq_check.py
"""
import itertools
import time

import numpy as np
import pandas as pd

from bb_scalp import simulate, pick, swing_test, tested

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 300)

YEARS = list(range(2020, 2027))
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
LENS = [15, 20, 30]
STDS = [2.75, 3.0, 3.25, 3.5]
TOLS = [0.15, 0.25, 0.4]
EXITS = [("1R", 1.0), ("1.5R", 1.5), ("2R", 2.0)]
SLS = [1.5, 2.0, 2.5, 3.0]
TBARS = [10, 20, 40]
OFFSETS = [0, 5, 10]
TF = 15
SLIP_PTS, COMM_PTS = 1.0, 1.24 / 2.0
FILTERS = ["(none)", "ema200", "any level + trend"]


class Market:
    def __init__(self, path, slip=SLIP_PTS, comm=COMM_PTS):
        self.slip, self.comm = slip, comm
        df = pd.read_parquet(path)
        df = df[~((df.volume == 0) & (df.high == df.low))]
        self.df, self.idx = df, df.index
        self.O, self.H, self.L, self.C, V = (df[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume"))
        self.n = len(df)
        self.year = self.idx.year.to_numpy()
        day = self.idx.floor("D")
        dcode, _ = pd.factorize(day)
        dg = df.groupby(dcode).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"))
        pdh, pdl, pdc = (dg[k].shift(1).to_numpy()[dcode] for k in ("h", "l", "c"))
        dopen = dg.o.to_numpy()[dcode]
        week = day - pd.to_timedelta(day.day_of_week, unit="D")
        wcode, _ = pd.factorize(week)
        wg = df.groupby(wcode).agg(h=("high", "max"), l=("low", "min"))
        self.weekly = np.column_stack([wg[k].shift(1).to_numpy()[wcode] for k in ("h", "l")])
        self.fibs = np.column_stack([pdl + f * (pdh - pdl) for f in (0.382, 0.5, 0.618)])
        self.daily = np.column_stack([pdh, pdl, pdc, dopen])
        tp = (self.H + self.L + self.C) / 3; w = V + 1e-9
        self.vwap = (pd.Series(tp * w).groupby(dcode).cumsum() / pd.Series(w).groupby(dcode).cumsum()).to_numpy()
        b60, e60 = self._resample(60, 0)
        tr = np.full(self.n, np.nan); tr[e60] = b60.close.ewm(span=200, adjust=False).mean().to_numpy()
        self.tr60 = pd.Series(tr).ffill().to_numpy()
        b15, e15 = self._resample(15, 0)
        h15, l15 = b15.high.to_numpy(), b15.low.to_numpy()
        ph = np.zeros(len(b15), bool); pl = np.zeros(len(b15), bool)
        c = slice(2, -2)
        ph[c] = (h15[c] > h15[:-4]) & (h15[c] > h15[1:-3]) & (h15[c] > h15[3:-1]) & (h15[c] > h15[4:])
        pl[c] = (l15[c] < l15[:-4]) & (l15[c] < l15[1:-3]) & (l15[c] < l15[3:-1]) & (l15[c] < l15[4:])
        pi = np.r_[np.where(ph)[0], np.where(pl)[0]]; plv = np.r_[h15[ph], l15[pl]]
        conf = e15[pi + 2]; o = np.argsort(conf, kind="stable")
        self.piv = (plv[o], conf[o].astype(np.int64), e15[pi][o].astype(np.int64))
        self.bars, self.sig = {}, {}

    def _resample(self, tf, offset):
        b = self.df.resample(f"{tf}min", label="left", closed="left", offset=f"{offset}min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        end = np.searchsorted(self.idx.values, (b.index + pd.Timedelta(minutes=tf)).values) - 1
        return b, end

    def tf_bars(self, off):
        if off not in self.bars:
            b, end = self._resample(TF, off)
            bc, bh, bl = b.close.to_numpy(), b.high.to_numpy(), b.low.to_numpy()
            pc = np.r_[np.nan, bc[:-1]]
            atr = pd.Series(np.nanmax(np.column_stack([bh - bl, np.abs(bh - pc), np.abs(bl - pc)]), axis=1)
                            ).rolling(14).mean().to_numpy()
            self.bars[off] = dict(b=b, end=end, bc=bc, bh=bh, bl=bl, atr=atr,
                                  sma=b.close.rolling(200).mean().to_numpy(),
                                  ema=b.close.ewm(span=200, adjust=False).mean().to_numpy())
        return self.bars[off]

    def signals(self, off, ln, k):
        key = (off, ln, k)
        if key not in self.sig:
            t = self.tf_bars(off)
            mid = t["b"].close.rolling(ln).mean().to_numpy()
            sd = t["b"].close.rolling(ln).std(ddof=0).to_numpy()
            up, dn = mid + k * sd, mid - k * sd
            lg = (t["bl"] <= dn) & (t["bc"] > dn); sh = (t["bh"] >= up) & (t["bc"] < up)
            bi = np.r_[np.where(lg)[0], np.where(sh)[0]]
            dr = np.r_[np.ones(lg.sum()), -np.ones(sh.sum())]
            o = np.argsort(bi, kind="stable"); bi, dr = bi[o], dr[o]
            pos = t["end"][bi].astype(np.int64)
            mid1m = np.full(self.n, np.nan); mid1m[t["end"]] = mid
            self.sig[key] = dict(bi=bi, pos=pos, dr=dr, lo=t["bl"][bi], hi=t["bh"][bi], cl=t["bc"][bi],
                                 atr=t["atr"][bi], mid1m=pd.Series(mid1m).ffill().to_numpy(),
                                 ema=t["ema"][bi], sma=t["sma"][bi])
        return self.sig[key]

    def masks(self, s, tol):
        tl = tol * s["atr"]
        T = lambda lv: tested(lv, s["dr"], s["lo"], s["hi"], s["cl"], tl)
        pos = s["pos"]
        g = [T(self.fibs[pos]), T(self.daily[pos]), T(self.weekly[pos]),
             swing_test(pos, s["dr"], s["lo"], s["hi"], s["cl"], tl, *self.piv, 2880, 12),
             T(s["sma"][:, None]), T(s["ema"][:, None]), T(self.vwap[pos][:, None])]
        anyl = np.any(g, axis=0)
        trend = np.sign(s["cl"] - self.tr60[pos]) == s["dr"]
        return {"(none)": np.ones(len(pos), bool), "ema200": g[5], "any level + trend": anyl & trend}

    def run(self, s, tp_r, slk, tb, delay=0, slip=None):
        slip = self.slip if slip is None else slip
        ret, xpos = simulate(s["pos"] + delay, s["dr"], s["atr"], self.O, self.H, self.L, self.C, s["mid1m"],
                             slk, tp_r, tb * TF)
        ent = self.O[np.minimum(s["pos"] + 1 + delay, self.n - 1)]
        return ret - (slip + self.comm) / ent * 100, xpos


def stats(r, y):
    out = {"trades": len(r), "all": r.mean() if len(r) else np.nan}
    for p, ys in PERIODS.items():
        sel = np.isin(y, list(ys))
        out[p] = r[sel].mean() if sel.any() else np.nan
    out["yrs>0"] = sum(r[y == yy].mean() > 0 for yy in YEARS if (y == yy).any())
    return out


def neighbourhood(m):
    rows = []
    for off, ln, k in itertools.product(OFFSETS, LENS, STDS):
        s = m.signals(off, ln, k)
        yrs = m.year[s["pos"]]
        mk = {tol: m.masks(s, tol) for tol in TOLS}
        for (ex, tp_r), slk, tb in itertools.product(EXITS, SLS, TBARS):
            ret, xpos = m.run(s, tp_r, slk, tb)
            for tol in TOLS:
                for f, msk in mk[tol].items():
                    if f == "(none)" and tol != TOLS[0]:
                        continue
                    tk = pick(s["pos"], xpos, msk)
                    rows.append({"offset": off, "len": ln, "std": k, "tol": tol if f != "(none)" else np.nan,
                                 "exit": ex, "sl": slk, "tbars": tb, "filter": f, **stats(ret[tk], yrs[tk])})
    return pd.DataFrame(rows)


def summarize(r, label, verbose):
    P = list(PERIODS)
    print(f"\n===== {label}: net % per trade after costs, nearby settings =====")
    g = r.groupby("filter")
    t = pd.DataFrame({
        "settings": g.size(),
        "trades/yr": (g.trades.median() / 6.87).round(0),
        **{f"median {p}": g[p].median().round(4) for p in P + ["all"]},
        "% net>0 all": (g["all"].apply(lambda x: (x > 0).mean()) * 100).round(0),
        "% net>0 every period": g.apply(lambda x: (x[P] > 0).all(axis=1).mean() * 100).round(0),
        "% >=6 of 7 yrs": (g["yrs>0"].apply(lambda x: (x >= 6).mean()) * 100).round(0),
    })
    print(t.to_string())
    dims = ["offset", "len", "std", "tol", "exit", "sl", "tbars"] if verbose else ["std", "offset"]
    for f in FILTERS[1:]:
        x = r[r["filter"] == f]
        for dim in dims:
            d = x.groupby(dim)[P + ["all"]].median().round(4)
            d["% every period>0"] = x.groupby(dim).apply(lambda z: (z[P] > 0).all(axis=1).mean() * 100).round(0)
            print(f"-- {f}, by {dim} --"); print(d.to_string())


def placebo(m, draws=2000, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for f, k, (ex, tp_r) in itertools.product(FILTERS[1:], [3.0, 3.25], EXITS):
        s = m.signals(0, 20, k)
        mk = m.masks(s, 0.25)[f]
        ret, xpos = m.run(s, tp_r, 2.0, 20)
        real = ret[pick(s["pos"], xpos, mk)].mean()
        N, ns = len(mk), mk.sum()
        sims = np.empty(draws)
        for i in range(draws):
            rm = np.zeros(N, bool); rm[rng.choice(N, ns, replace=False)] = True
            sims[i] = ret[pick(s["pos"], xpos, rm)].mean()
        rows.append({"filter": f, "std": k, "exit": ex, "filter net%": real, "random median": np.median(sims),
                     "random 95th": np.percentile(sims, 95), "p (random >= filter)": (sims >= real).mean()})
    return pd.DataFrame(rows)


def core(m):
    s = m.signals(0, 20, 3.0)
    mk = m.masks(s, 0.25)
    yrs = m.year[s["pos"]]
    rows = []
    for f in FILTERS:
        for label, kw in [("base", {}), ("1 min late", {"delay": 1}), ("2 min late", {"delay": 2}),
                          ("double slippage", {"slip": 2 * m.slip})]:
            ret, xpos = m.run(s, 1.5, 2.0, 20, **kw)
            tk = pick(s["pos"], xpos, mk[f])
            sides = [("both", tk)] + ([("long", tk & (s["dr"] > 0)), ("short", tk & (s["dr"] < 0))]
                                      if label == "base" else [])
            for side, t in sides:
                r, y = ret[t], yrs[t]
                rec = {"filter": f, "variant": label, "side": side, "trades": len(r), "net%": r.mean(),
                       "$/trade @50k": r.mean() / 100 * 50_000, "win%": (r > 0).mean() * 100}
                for yy in YEARS:
                    rec[yy] = r[y == yy].mean()
                rows.append(rec)
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    nq = Market("nq_1m_vol.parquet")
    print(f"loaded [{time.time() - t0:.0f}s]")
    nb = neighbourhood(nq)
    nb.to_parquet("bb_nq_check_nb.parquet")
    summarize(nb, "NQ", True)
    print(f"[{time.time() - t0:.0f}s]")
    print("\n===== Core: 15m, BB 20 / 3.0 reject, 1.5R, SL 2 ATR, 20 bars, tol 0.25: net % per trade by year =====")
    print(core(nq).round(4).to_string(index=False))
    print("\n===== Placebo: random filters keeping the same number of signals (BB 20, tol 0.25, SL 2 ATR, 20 bars) =====")
    print(placebo(nq).round(4).to_string(index=False))
    print(f"[{time.time() - t0:.0f}s]")
    es = Market("es_1m.parquet", slip=0.5, comm=1.24 / 5.0)   # MES: 2 ticks slippage, $1.24 at $5/pt
    summarize(neighbourhood(es), "ES (MES costs: 0.5 pt + $1.24)", False)
    print("\n===== ES core =====")
    print(core(es).round(4).to_string(index=False))
    print(f"[{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
