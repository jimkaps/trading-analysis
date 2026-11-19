"""Bollinger Band trend-following breakout, with market-structure filters, on BTC / NQ / ES / gold.

Signal, on a signal timeframe TF (5 / 15 / 60 min bars built from the 1m data, UTC):
  long : first close above the upper band (previous close was inside); short is the mirror.
Entry at the next 1-minute open; exits simulated on 1-minute bars (stop first if both hit in a minute):
  "2R" / "3R" : fixed target at 2 or 3 x the stop distance
  "mid"       : stop trails up to the middle band (exit when price comes back to the mean)
  "trail"     : chandelier trail, stop = best price since entry - stop distance
Stop distance = k x ATR14(TF), k = 1 / 1.5 / 2 / 3. Time stop after 50 TF bars.
One position at a time per (setting, filter).

Filters (market structure from fractal swing points, 2 bars each side, used only once confirmed):
  struct 15m / struct 60m : last two swing highs AND lows rising (HH + HL) for longs, falling for shorts
  BOS 15m                 : breakout close is also beyond the last confirmed 15m swing high / low
  BOS + struct 60m        : both
  against struct 60m      : 60m structure points the other way (sanity check)
  squeeze                 : band width (prior bar) in the lowest 20% of the last 500 TF bars
  squeeze + BOS, squeeze + struct 60m
  60m EMA200 trend        : price on the trade's side of the 60-min EMA200

Costs per round trip: BTC 0.05% of position; MNQ 1 pt + $1.24; MES 0.5 pt + $1.24; MGC 0.2 pt + $1.24.
Periods: select 2020-23, check 2024-25, final check 2026. $ figures on a fixed $50,000 position.

Usage: python bb_breakout.py            (all four markets)
       python bb_breakout.py --report   (re-print from bb_breakout_results.parquet)
"""
import itertools
import sys
import time

import numpy as np
import pandas as pd
from numba import njit

from bb_scalp import pick

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 300)

NOTIONAL = 50_000
YEARS = list(range(2020, 2027))
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
TFS = [5, 15, 60]
STDS = [2.0, 2.5, 3.0]
EXITS = [("2R", 0, 2.0), ("3R", 0, 3.0), ("mid", 1, 0.0), ("trail", 2, 0.0)]
SLS = [1.0, 1.5, 2.0, 3.0]
BB_LEN = 20
TIME_BARS = 50
MARKETS = {   # name: (file, drop filler bars, cost kind, value)
    "BTC": ("btc_1m.parquet", False, "pct", 0.05),
    "NQ": ("nq_1m_vol.parquet", True, "pts", 1.0 + 1.24 / 2.0),
    "ES": ("es_1m.parquet", True, "pts", 0.5 + 1.24 / 5.0),
    "Gold": ("gold_1m.parquet", True, "pts", 0.2 + 1.24 / 10.0),
}


@njit(cache=True)
def sim_trend(sig_pos, sig_dir, sig_atr, O, H, L, C, mid1m, sl_k, mode, tp_r, max_min):
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
        dist = sl_k * sig_atr[s]
        stop = e - d * dist
        tp = e + d * tp_r * dist
        ext = e
        end = min(p + max_min, n)
        x = np.nan
        xj = end - 1
        for j in range(p, end):
            if mode == 1:
                mm = mid1m[j - 1]
                if d > 0 and mm > stop:
                    stop = mm
                elif d < 0 and mm < stop:
                    stop = mm
            elif mode == 2 and j > p:
                if d > 0:
                    ext = max(ext, H[j - 1])
                    stop = max(stop, ext - dist)
                else:
                    ext = min(ext, L[j - 1])
                    stop = min(stop, ext + dist)
            if d > 0:
                if L[j] <= stop:
                    x = min(O[j], stop); xj = j; break
                if mode == 0 and H[j] >= tp:
                    x = max(O[j], tp); xj = j; break
            else:
                if H[j] >= stop:
                    x = max(O[j], stop); xj = j; break
                if mode == 0 and L[j] <= tp:
                    x = min(O[j], tp); xj = j; break
        if np.isnan(x):
            x = C[end - 1]
        ret[s] = d * (x - e) / e * 100.0
        xpos[s] = xj
    return ret, xpos


def resample(df, idx, tf):
    b = df.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    end = np.searchsorted(idx.values, (b.index + pd.Timedelta(minutes=tf)).values) - 1
    return b, end


def swings(df, idx, tf):
    """Fractal swing highs / lows (2 bars each side) as (confirm position, value), sorted by confirm time."""
    b, end = resample(df, idx, tf)
    h, l = b.high.to_numpy(), b.low.to_numpy()
    c = slice(2, -2)
    ph = np.zeros(len(b), bool); pl = np.zeros(len(b), bool)
    ph[c] = (h[c] > h[:-4]) & (h[c] > h[1:-3]) & (h[c] >= h[3:-1]) & (h[c] >= h[4:])
    pl[c] = (l[c] < l[:-4]) & (l[c] < l[1:-3]) & (l[c] <= l[3:-1]) & (l[c] <= l[4:])
    hi = np.where(ph)[0]; lo = np.where(pl)[0]
    return (end[hi + 2], h[hi]), (end[lo + 2], l[lo])


def last_two(sw, pos):
    conf, val = sw
    i = np.searchsorted(conf, pos, side="right") - 1      # confirmed at or before the signal minute
    last = np.where(i >= 0, val[np.clip(i, 0, None)], np.nan)
    prev = np.where(i >= 1, val[np.clip(i - 1, 0, None)], np.nan)
    return last, prev


def structure(sw_h, sw_l, pos):
    lh, ph = last_two(sw_h, pos)
    ll, pl = last_two(sw_l, pos)
    up = (lh > ph) & (ll > pl)
    dn = (lh < ph) & (ll < pl)
    return up, dn, lh, ll


def run_market(name):
    path, drop, ckind, cval = MARKETS[name]
    df = pd.read_parquet(path)
    if drop:
        df = df[~((df.volume == 0) & (df.high == df.low))]
    idx = df.index
    O, H, L, C = (df[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    n = len(df)
    year1m = idx.year.to_numpy()
    sw15 = swings(df, idx, 15); sw60 = swings(df, idx, 60)
    b60, e60 = resample(df, idx, 60)
    tr = np.full(n, np.nan); tr[e60] = b60.close.ewm(span=200, adjust=False).mean().to_numpy()
    tr60 = pd.Series(tr).ffill().to_numpy()

    rows = []
    for tf in TFS:
        b, end = resample(df, idx, tf)
        bc, bh, bl = b.close.to_numpy(), b.high.to_numpy(), b.low.to_numpy()
        pc = np.r_[np.nan, bc[:-1]]
        atr = pd.Series(np.nanmax(np.column_stack([bh - bl, np.abs(bh - pc), np.abs(bl - pc)]), axis=1)
                        ).rolling(14).mean().to_numpy()
        mid = b.close.rolling(BB_LEN).mean().to_numpy()
        sd = b.close.rolling(BB_LEN).std(ddof=0).to_numpy()
        bw = pd.Series(sd / mid)
        bw_rank = bw.rolling(500, min_periods=200).rank(pct=True).shift(1).to_numpy()
        mid1m = np.full(n, np.nan); mid1m[end] = mid
        mid1m = pd.Series(mid1m).ffill().to_numpy()
        for k in STDS:
            up, dn = mid + k * sd, mid - k * sd
            lg = (bc > up) & ~(np.r_[np.nan, bc[:-1]] > np.r_[np.nan, up[:-1]])
            sh = (bc < dn) & ~(np.r_[np.nan, bc[:-1]] < np.r_[np.nan, dn[:-1]])
            bi = np.r_[np.where(lg)[0], np.where(sh)[0]]
            dr = np.r_[np.ones(lg.sum()), -np.ones(sh.sum())]
            o = np.argsort(bi, kind="stable"); bi, dr = bi[o], dr[o]
            pos = end[bi].astype(np.int64)
            s_atr, s_cl = atr[bi], bc[bi]
            u15, d15, lh15, ll15 = structure(*sw15, pos)
            u60, d60, _, _ = structure(*sw60, pos)
            L_ = dr > 0
            st15 = np.where(L_, u15, d15)
            st60 = np.where(L_, u60, d60)
            anti60 = np.where(L_, d60, u60)
            bos = np.where(L_, s_cl > lh15, s_cl < ll15)
            sq = bw_rank[bi] < 0.2
            ema_ok = np.sign(s_cl - tr60[pos]) == dr
            filters = {"(none)": np.ones(len(pos), bool), "struct 15m": st15, "struct 60m": st60,
                       "BOS 15m": bos, "BOS + struct 60m": bos & st60, "against struct 60m": anti60,
                       "squeeze": sq, "squeeze + BOS": sq & bos, "squeeze + struct 60m": sq & st60,
                       "60m EMA200 trend": ema_ok}
            ent = O[np.minimum(pos + 1, n - 1)]
            cost = np.full(len(pos), cval) if ckind == "pct" else cval / ent * 100
            yrs = year1m[pos]
            for (ex, mode, tp_r), slk in itertools.product(EXITS, SLS):
                ret, xpos = sim_trend(pos, dr, s_atr, O, H, L, C, mid1m, slk, mode, tp_r, TIME_BARS * tf)
                net = ret - cost
                for fname, mask in filters.items():
                    tk = pick(pos, xpos, mask)
                    r, y = net[tk], yrs[tk]
                    rec = {"market": name, "tf": tf, "std": k, "exit": ex, "sl": slk, "filter": fname,
                           "trades": len(r), "net": r.mean() if len(r) else np.nan,
                           "gross": ret[tk].mean() if len(r) else np.nan,
                           "win": (r > 0).mean() if len(r) else np.nan,
                           "net long": r[dr[tk] > 0].mean() if (dr[tk] > 0).any() else np.nan,
                           "net short": r[dr[tk] < 0].mean() if (dr[tk] < 0).any() else np.nan,
                           "hold_min": (xpos[tk] - pos[tk]).mean() if len(r) else np.nan}
                    for yy in YEARS:
                        sel = y == yy
                        rec[f"s{yy}"] = r[sel].sum(); rec[f"n{yy}"] = int(sel.sum())
                    rows.append(rec)
    return rows


def add_periods(res):
    for p, ys in PERIODS.items():
        n = sum(res[f"n{y}"] for y in ys)
        res[f"n {p}"] = n
        res[p] = sum(res[f"s{y}"] for y in ys) / n.clip(lower=1)
        res[f"$ {p}"] = (sum(res[f"s{y}"] for y in ys) / 100 * NOTIONAL).round(0)
    res["ok"] = (res[list(PERIODS)] > 0).all(axis=1) & (res["n 2026"] >= 10)
    res["yrs>0"] = sum((res[f"s{y}"] > 0).astype(int) for y in YEARS)
    return res


def report(res):
    res = add_periods(res.copy())
    P = list(PERIODS)
    print("===== Net % per trade after costs: median over 144 settings (3 TF x 3 std x 4 exits x 4 stops) =====")
    g = res.groupby(["market", "filter"], sort=False)
    t = pd.DataFrame({"trades/yr": (g.trades.median() / 6.87).round(0),
                      **{f"med {p}": g[p].median().round(4) for p in P},
                      "med gross": g.gross.median().round(4),
                      "% net>0 every period": (g.ok.mean() * 100).round(0),
                      "% >=6 of 7 yrs": (g["yrs>0"].apply(lambda x: (x >= 6).mean()) * 100).round(0)})
    print(t.to_string())

    print("\n===== By timeframe and exit, no filter: median net % per trade (all years) =====")
    nf = res[res["filter"] == "(none)"]
    print(nf.pivot_table(index=["tf", "exit"], columns="market", values="net", aggfunc="median").round(4).to_string())

    for m in MARKETS:
        r = res[(res.market == m) & (res["n 2020-23"] >= 100)]
        top = r.sort_values("$ 2020-23", ascending=False).head(10)
        print(f"\n===== {m}: top 10 by 2020-23 net $ (min 100 trades), then out of sample =====")
        cols = ["tf", "std", "exit", "sl", "filter", "trades", "net", "win", "hold_min", "net long", "net short"] + \
               [f"$ {p}" for p in P] + [f"n {p}" for p in P]
        print(top[cols].round(4).to_string(index=False))
        print(f"  net > 0 in every period: {r.ok.sum()} of {len(r)}")

    print("\n===== Same setting positive in every period on how many markets? =====")
    key = ["tf", "std", "exit", "sl", "filter"]
    cnt = res.groupby(key).ok.sum()
    print(cnt.value_counts().sort_index().rename("settings").to_string())
    multi = cnt[cnt >= 2].index
    if len(multi):
        sub = res.set_index(key).loc[multi].reset_index()
        print(sub[key + ["market", "trades", "net", "net long", "net short"] + P + ["ok"]]
              .sort_values(key + ["market"]).round(4).to_string(index=False))
    print("\nBy filter: share of settings positive every period in >= 3 of 4 markets")
    print((res.groupby(key).ok.sum() >= 3).groupby("filter").mean().mul(100).round(1).to_string())


def main():
    if "--report" in sys.argv:
        report(pd.read_parquet("bb_breakout_results.parquet"))
        return
    t0 = time.time()
    rows = []
    for m in MARKETS:
        rows += run_market(m)
        print(f"{m} done [{time.time() - t0:.0f}s]")
    res = pd.DataFrame(rows)
    res.to_parquet("bb_breakout_results.parquet")
    report(res)


if __name__ == "__main__":
    main()
