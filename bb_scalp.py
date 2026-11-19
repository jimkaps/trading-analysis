"""Bollinger Band mean-reversion scalp on BTCUSD 1-minute data, with confluence filters.

Signal, on a signal timeframe TF (1 / 5 / 15 min bars built from the 1m data, UTC):
  "reject": long when the bar's low touches the lower band and it closes back inside;
            short is the mirror at the upper band.
  "close" : long when the bar closes below the lower band; short is the mirror.
Entry at the next 1-minute open. Exits are simulated on the 1-minute bars:
  SL = k x ATR14(TF) from entry.
  TP = middle band (the value known at the previous minute), or a fixed R multiple of the stop.
  Time stop after 20 TF bars. If SL and TP are both touched in the same minute, it counts as SL.
One position at a time per (setting, filter): signals during an open trade are skipped.
Results are % of position per trade; $ figures assume a fixed $50,000 position.
Fees are % of position per round trip. The data is Dukascopy BID, so the spread must
come out of the fee too.

Confluence: the signal bar "tests" a level, i.e. for a long the level lies between
(low - tol) and (close + tol), tol = 0.25 x ATR14(TF); a short is the mirror.
  fib    : prior UTC day's 38.2 / 50 / 61.8 % retracements
  daily  : prior day high / low / close, and today's open
  weekly : prior week high / low
  swing  : last 12 confirmed 15-min fractal pivots (2 bars each side) from the past 48h
  sma200 / ema200 : on the signal timeframe
  vwap   : daily UTC VWAP (Dukascopy tick volume)
  any level / 2+ levels : at least one / two of the groups above
Trend filters: price vs the 60-min EMA200 agrees / disagrees with the trade.

Periods: select on 2020-23, check 2024-25, final check 2026.

Usage: python bb_scalp.py btc_1m.parquet [out.parquet] [--drop-filler] [--mnq | --mgc | --mes] [--stds=3,3.5,4]
       python bb_scalp.py --report out.parquet [--mnq | --mgc | --mes]
  --drop-filler : drop flat zero-volume bars (closed-market filler in the index/futures data)
  --mnq         : also report net of MNQ costs (1 pt slippage + $1.24 commission per round
                  trip at $2/pt, converted to % of the entry price per trade)
  --mgc         : the same for micro gold (0.2 pt slippage + $1.24 at $10/pt)
  --mes         : the same for micro S&P (0.5 pt slippage + $1.24 at $5/pt)
"""
import sys
import time

import numpy as np
import pandas as pd
from numba import njit

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

NOTIONAL = 50_000
FEES = [0.0, 0.02, 0.05, 0.10]
YEARS = list(range(2020, 2027))
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
TFS = [1, 5, 15]
STDS = [2.0, 2.5, 3.0]
for _a in sys.argv:                      # --stds=3,3.5,4 overrides the band widths
    if _a.startswith("--stds="):
        STDS = [float(x) for x in _a.split("=", 1)[1].split(",")]
# Note: with a 20-bar population std that includes the current close, a close can be at most
# 19/sqrt(20) = 4.25 sigma from the mean, so "close" signals cannot exist beyond 4.25.
ENTRIES = ["reject", "close"]
EXITS = [("mid", 0.0), ("1R", 1.0), ("1.5R", 1.5)]
SLS = [1.0, 1.5, 2.0]
BB_LEN = 20
TIME_BARS = 20
TOL_ATR = 0.25
# futures cost per round trip in points: slippage + commission / $ per point
COSTS = {"--mnq": ("MNQ", 1.0 + 1.24 / 2.0, "1 pt + $1.24"), "--mgc": ("MGC", 0.2 + 1.24 / 10.0, "0.2 pt + $1.24"),
         "--mes": ("MES", 0.5 + 1.24 / 5.0, "0.5 pt + $1.24")}
FUT = next((COSTS[a] for a in sys.argv if a in COSTS), None)
COST_PTS = FUT[1] if FUT else COSTS["--mnq"][1]


@njit(cache=True)
def simulate(sig_pos, sig_dir, sig_atr, O, H, L, C, mid1m, sl_k, tp_r, max_min):
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
        sl = e - d * dist
        tp = e + d * tp_r * dist
        end = min(p + max_min, n)
        x = np.nan
        xj = end - 1
        for j in range(p, end):
            t = mid1m[j - 1] if tp_r == 0.0 else tp
            if d > 0:
                if L[j] <= sl:
                    x = min(O[j], sl); xj = j; break
                if H[j] >= t:
                    x = max(O[j], t); xj = j; break
            else:
                if H[j] >= sl:
                    x = max(O[j], sl); xj = j; break
                if L[j] <= t:
                    x = min(O[j], t); xj = j; break
        if np.isnan(x):
            x = C[end - 1]
        ret[s] = d * (x - e) / e * 100.0
        xpos[s] = xj
    return ret, xpos


@njit(cache=True)
def pick(sig_pos, xpos, mask):
    take = np.zeros(len(sig_pos), np.bool_)
    last = -1
    for s in range(len(sig_pos)):
        if mask[s] and xpos[s] >= 0 and sig_pos[s] + 1 > last:
            take[s] = True
            last = xpos[s]
    return take


@njit(cache=True)
def swing_test(sig_pos, sig_dir, lo, hi, cl, tol, piv_lvl, piv_conf, piv_pos, max_age, K):
    m = len(sig_pos)
    out = np.zeros(m, np.bool_)
    buf = np.full(K, np.nan)
    bpos = np.zeros(K, np.int64)
    cnt = 0
    q = 0
    for s in range(m):
        t = sig_pos[s]
        while q < len(piv_lvl) and piv_conf[q] <= t:
            buf[cnt % K] = piv_lvl[q]
            bpos[cnt % K] = piv_pos[q]
            cnt += 1
            q += 1
        for k in range(min(cnt, K)):
            if t - bpos[k] > max_age:
                continue
            lv = buf[k]
            if sig_dir[s] > 0:
                ok = lo[s] <= lv + tol[s] and cl[s] >= lv - tol[s]
            else:
                ok = hi[s] >= lv - tol[s] and cl[s] <= lv + tol[s]
            if ok:
                out[s] = True
                break
    return out


def resample(df, idx, tf):
    b = df.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    end = np.searchsorted(idx.values, (b.index + pd.Timedelta(minutes=tf)).values) - 1
    return b, end


def tested(lvl, d, lo, hi, cl, tol):
    d, lo, hi, cl, tol = (a[:, None] for a in (d, lo, hi, cl, tol))
    lg = (lo <= lvl + tol) & (cl >= lvl - tol)
    sh = (hi >= lvl - tol) & (cl <= lvl + tol)
    return np.where(d > 0, lg, sh).any(axis=1)


def main():
    t0 = time.time()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    df = pd.read_parquet(args[0])
    if "--drop-filler" in sys.argv:
        df = df[~((df.volume == 0) & (df.high == df.low))]
    out_path = args[1] if len(args) > 1 else "bb_scalp_results.parquet"
    idx = df.index
    O, H, L, C, V = (df[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume"))
    n = len(df)
    year1m = idx.year.to_numpy()

    # ---- 1m-level context ----
    day = idx.floor("D")
    dcode, dkeys = pd.factorize(day)
    dg = df.groupby(dcode).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"))
    pdh, pdl, pdc = (dg[k].shift(1).to_numpy()[dcode] for k in ("h", "l", "c"))
    dopen = dg.o.to_numpy()[dcode]
    week = (day - pd.to_timedelta(day.day_of_week, unit="D"))
    wcode, _ = pd.factorize(week)
    wg = df.groupby(wcode).agg(h=("high", "max"), l=("low", "min"))
    pwh, pwl = (wg[k].shift(1).to_numpy()[wcode] for k in ("h", "l"))
    rngd = pdh - pdl
    fibs = np.column_stack([pdl + f * rngd for f in (0.382, 0.5, 0.618)])
    daily = np.column_stack([pdh, pdl, pdc, dopen])
    weekly = np.column_stack([pwh, pwl])
    tp_ = (H + L + C) / 3
    w = V + 1e-9
    vwap = (pd.Series(tp_ * w).groupby(dcode).cumsum() / pd.Series(w).groupby(dcode).cumsum()).to_numpy()

    # 60-min EMA200 trend, known at the close of each hour
    b60, e60 = resample(df, idx, 60)
    tr60 = np.full(n, np.nan)
    tr60[e60] = b60.close.ewm(span=200, adjust=False).mean().to_numpy()
    tr60 = pd.Series(tr60).ffill().to_numpy()

    # 15-min fractal pivots (2 bars each side), confirmed 2 bars later
    b15, e15 = resample(df, idx, 15)
    h15, l15 = b15.high.to_numpy(), b15.low.to_numpy()
    ph = np.zeros(len(b15), bool); pl = np.zeros(len(b15), bool)
    ph[2:-2] = ((h15[2:-2] > h15[:-4]) & (h15[2:-2] > h15[1:-3]) & (h15[2:-2] > h15[3:-1]) & (h15[2:-2] > h15[4:]))
    pl[2:-2] = ((l15[2:-2] < l15[:-4]) & (l15[2:-2] < l15[1:-3]) & (l15[2:-2] < l15[3:-1]) & (l15[2:-2] < l15[4:]))
    pi = np.r_[np.where(ph)[0], np.where(pl)[0]]
    plv = np.r_[h15[ph], l15[pl]]
    pconf = e15[pi + 2]; ppos = e15[pi]
    o_ = np.argsort(pconf, kind="stable")
    piv_lvl, piv_conf, piv_pos = plv[o_], pconf[o_].astype(np.int64), ppos[o_].astype(np.int64)
    print(f"context built {time.time() - t0:.0f}s")

    rows = []
    for tf in TFS:
        b, end = resample(df, idx, tf)
        bo, bh, bl, bc = (b[c].to_numpy() for c in ("open", "high", "low", "close"))
        mid = b.close.rolling(BB_LEN).mean().to_numpy()
        sd = b.close.rolling(BB_LEN).std(ddof=0).to_numpy()
        prevc = np.r_[np.nan, bc[:-1]]
        trr = np.nanmax(np.column_stack([bh - bl, np.abs(bh - prevc), np.abs(bl - prevc)]), axis=1)
        atr = pd.Series(trr).rolling(14).mean().to_numpy()
        sma = b.close.rolling(200).mean().to_numpy()
        ema = b.close.ewm(span=200, adjust=False).mean().to_numpy()
        mid1m = np.full(n, np.nan); mid1m[end] = mid
        mid1m = pd.Series(mid1m).ffill().to_numpy()
        for k in STDS:
            up, dn = mid + k * sd, mid - k * sd
            for entry in ENTRIES:
                if entry == "reject":
                    lg = (bl <= dn) & (bc > dn); sh = (bh >= up) & (bc < up)
                else:
                    lg = bc < dn; sh = bc > up
                bi = np.r_[np.where(lg)[0], np.where(sh)[0]]
                dr = np.r_[np.ones(lg.sum()), -np.ones(sh.sum())]
                o_ = np.argsort(bi, kind="stable")
                bi, dr = bi[o_], dr[o_]
                pos = end[bi].astype(np.int64)
                s_lo, s_hi, s_cl, s_atr = bl[bi], bh[bi], bc[bi], atr[bi]
                tol = TOL_ATR * s_atr
                T = lambda lv: tested(lv, dr, s_lo, s_hi, s_cl, tol)
                g = {
                    "fib": T(fibs[pos]),
                    "daily": T(daily[pos]),
                    "weekly": T(weekly[pos]),
                    "swing": swing_test(pos, dr, s_lo, s_hi, s_cl, tol, piv_lvl, piv_conf, piv_pos, 2880, 12),
                    "sma200": T(sma[bi][:, None]),
                    "ema200": T(ema[bi][:, None]),
                    "vwap": T(vwap[pos][:, None]),
                }
                cnt = np.sum(list(g.values()), axis=0)
                trend_ok = np.sign(s_cl - tr60[pos]) == dr
                filters = {"(none)": np.ones(len(pos), bool), **g,
                           "any level": cnt >= 1, "2+ levels": cnt >= 2,
                           "with 60m trend": trend_ok, "against 60m trend": ~trend_ok & ~np.isnan(tr60[pos]),
                           "any level + with trend": (cnt >= 1) & trend_ok,
                           "any level + against trend": (cnt >= 1) & ~trend_ok}
                yrs = year1m[pos]
                cost = COST_PTS / O[np.minimum(pos + 1, n - 1)] * 100
                for ex_name, tp_r in EXITS:
                    for slk in SLS:
                        ret, xpos = simulate(pos, dr, s_atr, O, H, L, C, mid1m, slk, tp_r, TIME_BARS * tf)
                        for fname, mask in filters.items():
                            take = pick(pos, xpos, mask)
                            r = ret[take]; y = yrs[take]; cc = cost[take]
                            hold = (xpos[take] - pos[take]).mean() if take.any() else np.nan
                            rec = {"tf": tf, "std": k, "entry": entry, "exit": ex_name, "sl_atr": slk,
                                   "filter": fname, "trades": len(r), "gross_avg": r.mean() if len(r) else np.nan,
                                   "win_gross": (r > 0).mean() if len(r) else np.nan, "hold_min": hold}
                            for yy in YEARS:
                                sel = y == yy
                                rec[f"g{yy}"] = r[sel].sum(); rec[f"n{yy}"] = sel.sum(); rec[f"c{yy}"] = cc[sel].sum()
                            rows.append(rec)
        print(f"tf {tf}m done {time.time() - t0:.0f}s")

    res = pd.DataFrame(rows)
    res.to_parquet(out_path)
    report(res)


def net_usd(res, ys, fee):
    return sum(res[f"g{y}"] - fee * res[f"n{y}"] for y in ys) / 100 * NOTIONAL


def report(res):
    res = res.copy()
    for p, ys in PERIODS.items():
        res[f"n {p}"] = sum(res[f"n{y}"] for y in ys)
        res[f"avg% {p}"] = sum(res[f"g{y}"] for y in ys) / res[f"n {p}"].clip(lower=1)

    print("\n===== Gross edge per trade (% of position, before fees), mean over all settings =====")
    print("(breakeven round-trip fee = gross avg; a $50k position earns $5 per 0.01%)")
    g = res.groupby("filter", sort=False)
    t = pd.DataFrame({
        "trades/yr": (g.trades.mean() / 6.87).round(0),
        **{f"avg% {p}": g[f"avg% {p}"].mean().round(4) for p in PERIODS},
        "win% gross": (g.win_gross.mean() * 100).round(1),
        "% settings >0.02 all periods": g.apply(lambda x: ((x[[f"avg% {p}" for p in PERIODS]] > 0.02)
                                                         .all(axis=1)).mean() * 100).round(0),
    })
    print(t.to_string())

    print("\n===== By timeframe / entry / exit (no filter vs any level), mean gross % per trade, all years =====")
    res["avg% all"] = res[[f"g{y}" for y in YEARS]].sum(axis=1) / res.trades.clip(lower=1)
    sub = res[res["filter"].isin(["(none)", "any level", "2+ levels"])]
    print(sub.pivot_table(index=["tf", "entry", "exit"], columns="filter", values="avg% all", aggfunc="mean")
          .round(4).to_string())

    for fee in (0.02, 0.05):
        r = res[res["n 2020-23"] >= 300].copy()
        for p, ys in PERIODS.items():
            r[f"$ {p}"] = net_usd(r, ys, fee).round(0)
        top = r.sort_values("$ 2020-23", ascending=False).head(15)
        print(f"\n===== Top 15 by 2020-23 net at {fee}% round-trip fee (min 300 trades), then out of sample =====")
        cols = ["tf", "std", "entry", "exit", "sl_atr", "filter", "trades", "gross_avg", "win_gross", "hold_min"] + \
               [f"$ {p}" for p in PERIODS] + [f"n {p}" for p in PERIODS]
        print(top[cols].round(4).to_string(index=False))
        print(f"  settings with net > 0 in all three periods at {fee}%: "
              f"{((r[[f'$ {p}' for p in PERIODS]] > 0).all(axis=1)).sum()} of {len(r)}")

    if FUT and "c2020" in res:
        print(f"\n===== Net of {FUT[0]} costs ({FUT[2]} per round trip), avg % per trade, mean over all settings =====")
        for p, ys in PERIODS.items():
            res[f"net% {p}"] = sum(res[f"g{y}"] - res[f"c{y}"] for y in ys) / res[f"n {p}"].clip(lower=1)
        res["cost% avg"] = res[[f"c{y}" for y in YEARS]].sum(axis=1) / res.trades.clip(lower=1)
        g = res.groupby("filter", sort=False)
        print(pd.DataFrame({"cost%/trade": g["cost% avg"].mean().round(4),
                            **{f"net% {p}": g[f"net% {p}"].mean().round(4) for p in PERIODS},
                            "% settings net>0 all periods": g.apply(
                                lambda x: (x[[f"net% {p}" for p in PERIODS]] > 0).all(axis=1).mean() * 100).round(1)
                            }).to_string())
        r = res[res["n 2020-23"] >= 300].copy()
        for p in PERIODS:
            r[f"$ {p}"] = (r[f"net% {p}"] * r[f"n {p}"] / 100 * NOTIONAL).round(0)
        top = r.sort_values("$ 2020-23", ascending=False).head(15)
        print(f"\n===== Top 15 by 2020-23 net of {FUT[0]} costs (min 300 trades), then out of sample, $50k position =====")
        cols = ["tf", "std", "entry", "exit", "sl_atr", "filter", "trades", "gross_avg", "win_gross", "hold_min"] + \
               [f"$ {p}" for p in PERIODS] + [f"n {p}" for p in PERIODS]
        print(top[cols].round(4).to_string(index=False))
        ok = (r[[f"$ {p}" for p in PERIODS]] > 0).all(axis=1)
        print(f"  settings net > 0 in all three periods: {ok.sum()} of {len(r)}")
        if ok.any():
            print(r[ok].sort_values("$ 2024-25", ascending=False)[cols].head(20).round(4).to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        report(pd.read_parquet(sys.argv[2]))
    else:
        main()
