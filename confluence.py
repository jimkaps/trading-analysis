"""Test confluence filters on the morning ORB (preset D and its neighbourhood).

Each filter keeps only days where a condition holds. It is judged on 72 nearby
settings (start 07:15/07:30/07:45, range 45/60/90 min, TP 2%/none, SL 0.75%/1%,
exit 19:30/20:55), per period (2020-23 / 2024-25 / 2026) and per year.

Usage: python confluence.py nq_1m.parquet
"""
import sys

import numpy as np
import pandas as pd

import orb_sweep as s

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

STARTS = [435, 450, 465]
LENS = [45, 60, 90]
EXITS = np.array([1170, 1255])
TPK = np.array([0, 0]); TPV = np.array([2.0, 99.0])
SLK = np.array([0, 0]); SLV = np.array([0.75, 1.0])
D_KEY = (450, 60, 1255, 99.0, 1.0)
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}


def last_valid(row_vals):
    """Last non-NaN per row."""
    idx = np.where(~np.isnan(row_vals), np.arange(row_vals.shape[1]), -1).max(axis=1)
    out = np.full(row_vals.shape[0], np.nan)
    ok = idx >= 0
    out[ok] = row_vals[np.arange(len(idx))[ok], idx[ok]]
    return out


def main():
    df = pd.read_parquet(sys.argv[1])
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    nd = len(days)
    years = days.year.to_numpy()

    # ---- day-level context (London clock) ----
    us_close = last_valid(C[:, :1260])                         # last price before 21:00
    us_open = O[:, 870]                                         # 14:30
    day_hi = np.nanmax(H[:, :1260], axis=1); day_lo = np.nanmin(L[:, :1260], axis=1)
    prev = lambda a: np.r_[np.nan, a[:-1]]
    p_close, p_open, p_hi, p_lo = prev(us_close), prev(us_open), prev(day_hi), prev(day_lo)
    on_hi = np.nanmax(H[:, 0:420], axis=1); on_lo = np.nanmin(L[:, 0:420], axis=1)  # 00:00-07:00
    mid_open = O[:, 0]
    atr = pd.Series(day_hi - day_lo).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    atr_long = pd.Series(day_hi - day_lo).rolling(100, min_periods=50).mean().shift(1).to_numpy()
    sma20 = pd.Series(us_close).rolling(20, min_periods=15).mean().shift(1).to_numpy()
    flatC = pd.Series(C.ravel()).ffill()
    ema250 = flatC.ewm(span=250, adjust=False).mean().to_numpy().reshape(C.shape)
    dow = days.weekday.to_numpy()

    rows = []
    for rs in STARTS:
        for ln in LENS:
            re_ = rs + ln
            pnl, dirs, width, ref, ents, pxs = s.run_block_full(O, H, L, C, rs, re_, EXITS, TPK, TPV, SLK, SLV,
                                                                s.COST_PTS)
            usd = pnl.astype(float) * s.PT_VALUE - s.COMMISSION        # [day, exit, tp, sl]
            dr = dirs.astype(float)
            price0 = O[:, rs]
            pre = C[:, re_ - 1]
            agree = lambda x: np.sign(x) == dr
            f = {
                "gap vs prior US close agrees": agree(price0 - p_close),
                "prior US session direction agrees": agree(p_close - p_open),
                "overnight drift (00:00->range) agrees": agree(price0 - mid_open),
                "above/below 20-day avg agrees": agree(pre - sma20),
                "intraday EMA(250 min) agrees": agree(pre - ema250[:, re_ - 1]),
                "entry beyond overnight high/low": np.where(dr > 0, pxs > on_hi, pxs < on_lo),
                "entry beyond prior-day high/low": np.where(dr > 0, pxs > p_hi, pxs < p_lo),
                "entry inside prior-day range": (pxs <= p_hi) & (pxs >= p_lo),
                "range < 0.5x ATR14 (tight)": width / atr < 0.5,
                "range not > 0.8x ATR14": ~(width / atr > 0.8),
                "high-vol regime (ATR14>ATR100)": atr > atr_long,
                "low-vol regime (ATR14<ATR100)": atr < atr_long,
                "breakout within 60 min of range end": (ents >= 0) & (ents < re_ + 60),
                "breakout within 120 min": (ents >= 0) & (ents < re_ + 120),
                "breakout after 120 min": ents >= re_ + 120,
                "skip Mondays": dow != 0,
                "skip Fridays": dow != 4,
                "long only": dr > 0,
            }
            # contrarian versions of directional confluences
            for k in list(f)[:5]:
                f["NOT " + k] = ~f[k] & (dirs != 0)
            for ei, ex in enumerate(EXITS):
                for ti in range(len(TPV)):
                    for si in range(len(SLV)):
                        base = usd[:, ei, ti, si]
                        traded = ~np.isnan(base)
                        key = (rs, ln, int(ex), TPV[ti], SLV[si])
                        for name, mask in [("(none)", np.ones(nd, bool))] + list(f.items()):
                            v = np.where(traded & mask, base, 0.0)
                            eq = np.cumsum(v)
                            dd = (np.maximum.accumulate(eq) - eq).max()
                            rec = {"setting": key, "filter": name, "trades": int((traded & mask).sum()),
                                   "wins": int(((v > 0) & traded & mask).sum()), "maxdd": dd,
                                   "total": v.sum()}
                            for y in range(2020, 2027):
                                rec[y] = v[years == y].sum()
                            rows.append(rec)
    r = pd.DataFrame(rows)
    for p, ys in PERIODS.items():
        r[p] = r[list(ys)].sum(axis=1)
    r["ret_dd"] = r.total / r.maxdd.clip(lower=1)

    base = r[r["filter"] == "(none)"].set_index("setting")
    out = []
    for name, g in r[r["filter"] != "(none)"].groupby("filter"):
        g = g.set_index("setting")
        b = base.loc[g.index]
        row = {"filter": name, "trades kept": f"{g.trades.sum() / b.trades.sum():.0%}"}
        for p in PERIODS:
            d = g[p] - b[p]
            row[f"{p} $chg"] = round(d.mean())
            row[f"{p} %better"] = f"{(d > 0).mean():.0%}"
        yd = (g[list(range(2020, 2027))] - b[list(range(2020, 2027))]).mean()
        row["years better"] = f"{(yd > 0).sum()}/7"
        row["ret/DD chg"] = round((g.ret_dd - b.ret_dd).mean(), 2)
        row["%ret/DD better"] = f"{((g.ret_dd - b.ret_dd) > 0).mean():.0%}"
        row["$/trade chg"] = round((g.total / g.trades.clip(lower=1) - b.total / b.trades.clip(lower=1)).mean(), 1)
        out.append(row)
    res = pd.DataFrame(out).sort_values("ret/DD chg", ascending=False)
    print("Baseline (72 settings) mean: " + ", ".join(f"{p} ${base[p].mean():,.0f}" for p in PERIODS)
          + f", ret/DD {base.ret_dd.mean():.2f}, $/trade {(base.total / base.trades).mean():.1f}")
    print(res.to_string(index=False))
    r.to_pickle("confluence_rows.pkl")

    d = r[r.setting == D_KEY].set_index("filter")
    print("\nPreset D itself:")
    print(d[["trades", "maxdd", "total", "ret_dd"] + list(range(2020, 2027))].round(1)
          .sort_values("ret_dd", ascending=False).to_string())


if __name__ == "__main__":
    main()
