"""EMA / SMA / VWAP as (1) entry filters and (2) trailing exits for the morning ORB (preset D neighbourhood).

Intraday averages are computed on the continuous 1-minute series; an N-bar average on a
5-minute chart is approximated by a 5N-minute average (60N for 1-hour). VWAP needs a
'volume' column (Dukascopy tick volume); without it VWAP tests are skipped.

Usage: python ma_test.py DATA.parquet
"""
import sys

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)

STARTS = [435, 450, 465]
LENS = [45, 60, 90]
EXITS = np.array([1170, 1255])
TPK = np.array([0, 0]); TPV = np.array([2.0, 99.0])
SLK = np.array([0, 0]); SLV = np.array([0.75, 1.0])
D_KEY = (450, 60, 1255, 99.0, 1.0)
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
YRS = list(range(2020, 2027))


def matrices(df):
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    V = None
    if "volume" in df.columns:
        loc = df.tz_convert("Europe/London")
        d = loc.index.normalize().tz_localize(None)
        di = pd.Index(days).get_indexer(d)
        mins = (loc.index.hour * 60 + loc.index.minute).to_numpy()
        V = np.zeros(O.shape)
        V[di, mins] = loc["volume"].to_numpy()
    return days, O, H, L, C, V


def build_lines(days, O, H, L, C, V):
    """Return dict name -> [day, minute] array of indicator values (no look-ahead: value at minute m uses data <= m)."""
    shape = C.shape
    flat = pd.Series(C.ravel()).ffill()
    lines = {}
    for n in (9, 20, 50, 100, 200):
        lines[f"EMA{n} 5m"] = flat.ewm(span=5 * n, adjust=False).mean().to_numpy().reshape(shape)
        lines[f"SMA{n} 5m"] = flat.rolling(5 * n, min_periods=5 * n // 2).mean().to_numpy().reshape(shape)
    lines["EMA21 5m"] = flat.ewm(span=105, adjust=False).mean().to_numpy().reshape(shape)
    for n in (20, 50, 200):
        lines[f"EMA{n} 1h"] = flat.ewm(span=60 * n, adjust=False).mean().to_numpy().reshape(shape)
        lines[f"SMA{n} 1h"] = flat.rolling(60 * n, min_periods=30 * n).mean().to_numpy().reshape(shape)
    if V is not None:
        tp = ((pd.Series(H.ravel()).ffill() + pd.Series(L.ravel()).ffill() + flat) / 3).to_numpy()
        vol = np.nan_to_num(V.ravel())
        minute_abs = np.arange(len(vol))
        for label, anchor in [("VWAP from 23:00 (futures session)", 23 * 60), ("VWAP from 00:00", 0),
                              ("VWAP from 07:00", 7 * 60)]:
            grp = (minute_abs - anchor) // 1440
            pv = pd.Series(tp * vol).groupby(grp).cumsum().to_numpy()
            vv = pd.Series(vol).groupby(grp).cumsum().to_numpy()
            with np.errstate(invalid="ignore", divide="ignore"):
                lines[label] = np.where(vv > 0, pv / vv, np.nan).reshape(shape)
    return lines


def daily_lines(C):
    us_close = pd.Series([r[~np.isnan(r)][-1] if (~np.isnan(r)).any() else np.nan for r in C[:, :1260]])
    out = {}
    for n in (10, 20, 50, 100, 200):
        out[f"daily SMA{n}"] = us_close.rolling(n, min_periods=int(n * 0.8)).mean().shift(1).to_numpy()
        out[f"daily EMA{n}"] = us_close.ewm(span=n, adjust=False).mean().shift(1).to_numpy()
    return out


@njit
def trail_block(O, H, L, C, line, dirs, ents, pxs, ex, sl_pct, cost_pts, step):
    """Exit when a completed `step`-minute bar closes on the wrong side of `line`; SL and time exit still apply."""
    nd = O.shape[0]
    out = np.full(nd, np.nan)
    for d in range(nd):
        side = dirs[d]; ent = ents[d]
        if side == 0 or ent < 0 or ent >= ex:
            continue
        px = pxs[d]
        sld = px * sl_pct / 100.0
        res = np.nan
        lastc = px
        for m in range(ent, ex):
            h = H[d, m]
            if h != h:
                continue
            lastc = C[d, m]
            if side == 1 and L[d, m] <= px - sld:
                res = -sld; break
            if side == -1 and h >= px + sld:
                res = -sld; break
            if m > ent and (m + 1) % step == 0:
                v = line[d, m]
                if v == v:
                    if side == 1 and lastc < v:
                        res = lastc - px; break
                    if side == -1 and lastc > v:
                        res = px - lastc; break
        if res != res:
            res = (lastc - px) * side
        out[d] = res - cost_pts
    return out


def summarise(rows):
    r = pd.DataFrame(rows)
    for p, ys in PERIODS.items():
        r[p] = r[list(ys)].sum(axis=1)
    r["ret_dd"] = r.total / r.maxdd.clip(lower=1)
    base = r[r["test"] == "(none)"].set_index("setting")
    out = []
    for name, g in r[r["test"] != "(none)"].groupby("test"):
        g = g.set_index("setting")
        b = base.loc[g.index]
        row = {"test": name, "trades kept": f"{g.trades.sum() / b.trades.sum():.0%}"}
        allp = True
        for p in PERIODS:
            dlt = g[p] - b[p]
            row[f"{p} $chg"] = round(dlt.mean())
            row[f"{p} %better"] = f"{(dlt > 0).mean():.0%}"
            allp &= (dlt > 0).mean() >= 0.6
        yd = (g[YRS] - b[YRS]).mean()
        row["yrs better"] = f"{(yd > 0).sum()}/7"
        row["ret/DD chg"] = round((g.ret_dd - b.ret_dd).mean(), 2)
        row["PASS"] = "YES" if allp and (yd > 0).sum() >= 5 else ""
        out.append(row)
    print("Baseline mean: " + ", ".join(f"{p} ${base[p].mean():,.0f}" for p in PERIODS)
          + f", ret/DD {base.ret_dd.mean():.2f}")
    print(pd.DataFrame(out).sort_values("ret/DD chg", ascending=False).to_string(index=False))
    return r


def rec(key, name, v, traded, years):
    v = np.where(traded, v, 0.0)
    eq = np.cumsum(v)
    d = {"setting": key, "test": name, "trades": int(traded.sum()), "maxdd": (np.maximum.accumulate(eq) - eq).max(),
         "total": v.sum()}
    for y in YRS:
        d[y] = v[years == y].sum()
    return d


def main():
    df = pd.read_parquet(sys.argv[1])
    days, O, H, L, C, V = matrices(df)
    lines = build_lines(days, O, H, L, C, V)
    dl = daily_lines(C)
    wk = (days.weekday < 5)
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    lines = {k: v[wk] for k, v in lines.items()}
    dl = {k: v[wk] for k, v in dl.items()}
    years = days.year.to_numpy()
    nd = len(days)
    ar = np.arange(nd)

    filt_rows, trail_rows = [], []
    for rs in STARTS:
        for ln in LENS:
            re_ = rs + ln
            pnl, dirs, width, ref, ents, pxs = s.run_block_full(O, H, L, C, rs, re_, EXITS, TPK, TPV, SLK, SLV,
                                                                s.COST_PTS)
            usd = pnl.astype(float) * s.PT_VALUE - s.COMMISSION
            dr = dirs.astype(float)
            e1 = np.clip(ents - 1, 0, 1439)            # minute before the entry bar
            pre = C[ar, e1]
            f = {}
            for k, ln_arr in lines.items():
                val = ln_arr[ar, e1]
                f[f"price vs {k} agrees"] = np.sign(pre - val) == dr
                if "VWAP" not in k:
                    slope = val - ln_arr[ar, np.clip(e1 - 30, 0, 1439)]
                    f[f"{k} slope agrees"] = np.sign(slope) == dr
            for k, val in dl.items():
                f[f"price vs {k} agrees"] = np.sign(pre - val) == dr
            f["EMA9>EMA21 5m agrees"] = np.sign(lines["EMA9 5m"][ar, e1] - lines["EMA21 5m"][ar, e1]) == dr
            f["EMA20>EMA50 1h agrees"] = np.sign(lines["EMA20 1h"][ar, e1] - lines["EMA50 1h"][ar, e1]) == dr
            f["daily SMA50>SMA200 agrees"] = np.sign(dl["daily SMA50"] - dl["daily SMA200"]) == dr
            f["daily EMA20>EMA50 agrees"] = np.sign(dl["daily EMA20"] - dl["daily EMA50"]) == dr
            for ei, ex in enumerate(EXITS):
                for ti in range(len(TPV)):
                    for si in range(len(SLV)):
                        base = usd[:, ei, ti, si]
                        traded = ~np.isnan(base)
                        key = (rs, ln, int(ex), TPV[ti], SLV[si])
                        filt_rows.append(rec(key, "(none)", base, traded, years))
                        for name, m in f.items():
                            filt_rows.append(rec(key, name, base, traded & m, years))
                # trailing exits (no TP)
                for si in range(len(SLV)):
                    key = (rs, ln, int(ex), 99.0, SLV[si])
                    base = usd[:, ei, 1, si]
                    traded = ~np.isnan(base)
                    trail_rows.append(rec(key, "(none)", base, traded, years))
                    trail_lines = ["EMA9 5m", "EMA20 5m", "EMA50 5m", "EMA100 5m", "EMA200 5m", "SMA20 5m",
                                   "SMA50 5m", "EMA20 1h", "EMA50 1h"] + [k for k in lines if "VWAP" in k]
                    for k in trail_lines:
                        step = 60 if "1h" in k else 5
                        p = trail_block(O, H, L, C, lines[k], dirs, ents, pxs, int(ex), SLV[si], s.COST_PTS, step)
                        v = p * s.PT_VALUE - s.COMMISSION
                        trail_rows.append(rec(key, f"trail exit on {k}", v, ~np.isnan(v), years))
        print(f"start {rs // 60:02d}:{rs % 60:02d} done", flush=True)

    print("\n===== (1) Moving averages / VWAP as entry filters (72 settings around D) =====")
    fr = summarise(filt_rows)
    print("\n===== (2) Moving averages / VWAP as trailing exits instead of holding to the exit time (36 settings) =====")
    tr = summarise(trail_rows)
    for name, r in [("filters", fr), ("trailing exits", tr)]:
        d = r[r.setting == D_KEY].sort_values("ret_dd", ascending=False).head(8)
        print(f"\nPreset D itself, best {name} by return/drawdown:")
        print(d[["test", "trades", "maxdd", "total", "ret_dd"] + YRS].round(1).to_string(index=False))
    fr.to_pickle("ma_filter_rows.pkl"); tr.to_pickle("ma_trail_rows.pkl")


if __name__ == "__main__":
    main()
