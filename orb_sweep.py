"""Opening-range-breakout parameter sweep on 1-minute Nasdaq-100 data.

Rules (match nq_orb_strategy.pine):
  * Range = high/low of minutes [start, start+len) in the anchor timezone.
  * From range end until exit time: stop entry at range high (long) / low (short),
    first breakout only, one trade per day.
  * TP / SL from entry price, either % of price, R-multiples of range width,
    or SL at the opposite side of the range.
  * Flat at the exit time. TP and SL in the same minute counts as a loss.
  * Costs per round trip, 1 MNQ ($2/pt): 1 pt slippage + $1.24 commission.

Filters layered on top (cheap, applied per trade):
  dir   : both / long-only / short-only
  trend : none / with-trend (breakout direction agrees with price vs 20-day mean)
  width : all / skip wide ranges (>1.5x 20-day median) / skip narrow (<0.7x)

Periods: select 2020-2023, validate 2024-2025, final check 2026.

Usage: python orb_sweep.py nq_1m.parquet results.parquet
"""
import sys
import time

import numpy as np
import pandas as pd
from numba import njit

PT_VALUE = 2.0          # MNQ $ per point
COST_PTS = 1.0          # slippage, points per round trip
COMMISSION = 1.24       # $ per round trip

TP_PCT = [0.3, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 99.0]   # 99 = no TP
TP_R = [1.0, 2.0, 3.0]
SL_PCT = [0.25, 0.35, 0.5, 0.75, 1.0]
# encode: kind 0 = pct, 1 = R multiple, 2 = opposite side of range
TP_KIND = np.array([0] * len(TP_PCT) + [1] * len(TP_R), dtype=np.int64)
TP_VAL = np.array(TP_PCT + TP_R, dtype=np.float64)
SL_KIND = np.array([0] * len(SL_PCT) + [2], dtype=np.int64)
SL_VAL = np.array(SL_PCT + [0.0], dtype=np.float64)
TP_LABEL = [f"{v}%" if v < 99 else "none" for v in TP_PCT] + [f"{v:g}R" for v in TP_R]
SL_LABEL = [f"{v}%" for v in SL_PCT] + ["range"]

GRIDS = {
    "London": dict(
        tz="Europe/London",
        starts=list(range(7 * 60, 16 * 60 + 1, 15)),
        lens=[15, 30, 45, 60, 90],
        exits=[16 * 60, 17 * 60, 18 * 60, 18 * 60 + 30, 19 * 60 + 30, 20 * 60 + 55],
    ),
    "NewYork": dict(
        tz="America/New_York",
        starts=list(range(8 * 60, 11 * 60 + 1, 15)),
        lens=[15, 30, 45, 60, 90],
        exits=[11 * 60, 12 * 60, 13 * 60, 13 * 60 + 30, 14 * 60 + 30, 15 * 60 + 55],
    ),
}


def day_matrix(df: pd.DataFrame, tz: str):
    loc = df.tz_convert(tz)
    d = loc.index.normalize()
    mins = (loc.index.hour * 60 + loc.index.minute).to_numpy()
    days, di = np.unique(d.tz_localize(None).to_numpy(), return_inverse=True)
    H = np.full((len(days), 1440), np.nan)
    L = H.copy(); O = H.copy(); C = H.copy()
    H[di, mins] = loc["high"].to_numpy()
    L[di, mins] = loc["low"].to_numpy()
    O[di, mins] = loc["open"].to_numpy()
    C[di, mins] = loc["close"].to_numpy()
    return pd.DatetimeIndex(days), O, H, L, C


@njit
def run_block_full(O, H, L, C, rs, re_, exits, tp_kind, tp_val, sl_kind, sl_val, cost_pts):
    """Return pnl_pts[day, exit, tp, sl] (nan = no trade), dir[day], width[day], ref[day]."""
    nd = O.shape[0]
    ne, nt, ns = len(exits), len(tp_val), len(sl_val)
    pnl = np.full((nd, ne, nt, ns), np.nan, dtype=np.float32)
    dirs = np.zeros(nd, dtype=np.int8)
    ents = np.full(nd, -1, dtype=np.int64)
    pxs = np.full(nd, np.nan)
    width = np.full(nd, np.nan)
    ref = np.full(nd, np.nan)   # price at range start, for trend filter
    max_ex = exits.max()
    cmax = np.empty(1440); cmin = np.empty(1440)
    for d in range(nd):
        rh = -1e18; rl = 1e18; nflat = 0; nbar = 0
        for m in range(rs, re_):
            h = H[d, m]
            if h == h:
                nbar += 1
                if h > rh: rh = h
                if L[d, m] < rl: rl = L[d, m]
                if h == L[d, m]: nflat += 1
                if ref[d] != ref[d]: ref[d] = O[d, m]
        if nbar < (re_ - rs) * 0.8 or nflat > nbar * 0.5 or rh <= rl:
            continue  # holiday / thin / filler data
        width[d] = rh - rl
        # find first breakout
        ent = -1; side = 0; px = 0.0
        for m in range(re_, max_ex):
            h = H[d, m]
            if h != h:
                continue
            o = O[d, m]; lo = L[d, m]
            up = h >= rh; dn = lo <= rl
            if up or dn:
                if o >= rh:
                    side = 1; px = o
                elif o <= rl:
                    side = -1; px = o
                elif up and dn:
                    if rh - o <= o - rl:
                        side = 1; px = rh
                    else:
                        side = -1; px = rl
                elif up:
                    side = 1; px = rh
                else:
                    side = -1; px = rl
                ent = m
                break
        if ent < 0:
            continue
        dirs[d] = side; ents[d] = ent; pxs[d] = px
        # favourable / adverse running extremes from the entry bar on
        fav = -1e18; adv = 1e18
        last = ent
        lastc = np.empty(1440)
        lc = px
        for m in range(ent, max_ex):
            h = H[d, m]
            if h == h:
                if side == 1:
                    f = h; a = L[d, m]
                else:
                    f = -L[d, m]; a = -h
                if f > fav: fav = f
                if a < adv: adv = a
                lc = C[d, m]
            cmax[m] = fav; cmin[m] = adv; lastc[m] = lc
        sp = px * side  # entry in "signed" space
        w = rh - rl
        for ei in range(ne):
            ex = exits[ei]
            if ex <= ent:
                continue
            end = ex - 1
            exit_close_signed = lastc[end] * side
            for ti in range(nt):
                if tp_kind[ti] == 0:
                    tpd = px * tp_val[ti] / 100.0
                elif tp_kind[ti] == 3:
                    tpd = tp_val[ti]
                else:
                    tpd = w * tp_val[ti]
                tpl = sp + tpd
                # first index with cmax >= tpl (binary search, cmax nondecreasing)
                lo_i = ent; hi_i = ex
                while lo_i < hi_i:
                    mid = (lo_i + hi_i) // 2
                    if cmax[mid] >= tpl:
                        hi_i = mid
                    else:
                        lo_i = mid + 1
                t_hit = lo_i
                for si in range(ns):
                    if sl_kind[si] == 0:
                        sld = px * sl_val[si] / 100.0
                    elif sl_kind[si] == 3:
                        sld = sl_val[si]
                    else:
                        sld = (px - rl) if side == 1 else (rh - px)
                        if sld <= 0:
                            sld = w
                    sll = sp - sld
                    lo_i = ent; hi_i = ex
                    while lo_i < hi_i:
                        mid = (lo_i + hi_i) // 2
                        if cmin[mid] <= sll:
                            hi_i = mid
                        else:
                            lo_i = mid + 1
                    s_hit = lo_i
                    if s_hit < ex and s_hit <= t_hit:
                        r = -sld
                    elif t_hit < ex:
                        r = tpd
                    else:
                        r = exit_close_signed - sp
                    pnl[d, ei, ti, si] = r - cost_pts
    return pnl, dirs, width, ref, ents, pxs


@njit
def run_block(O, H, L, C, rs, re_, exits, tp_kind, tp_val, sl_kind, sl_val, cost_pts):
    p, d, w, r, e, x = run_block_full(O, H, L, C, rs, re_, exits, tp_kind, tp_val, sl_kind, sl_val, cost_pts)
    return p, d, w, r


@njit
def stats_block(pnl_usd, keep, year_idx, n_years):
    """pnl_usd[day, k] with day mask keep[day]; returns per-k yearly sums, trades, wins, maxdd."""
    nd, nk = pnl_usd.shape
    ys = np.zeros((nk, n_years)); tr = np.zeros(nk); wn = np.zeros(nk); dd = np.zeros(nk)
    for k in range(nk):
        eq = 0.0; peak = 0.0; mdd = 0.0
        for d in range(nd):
            v = pnl_usd[d, k]
            if keep[d] and v == v:
                ys[k, year_idx[d]] += v
                tr[k] += 1
                if v > 0: wn[k] += 1
                eq += v
                if eq > peak: peak = eq
                if peak - eq > mdd: mdd = peak - eq
        dd[k] = mdd
    return ys, tr, wn, dd


def main():
    src, out = sys.argv[1], sys.argv[2]
    df = pd.read_parquet(src)
    rows = []
    t0 = time.time()
    for anchor, g in GRIDS.items():
        days, O, H, L, C = day_matrix(df, g["tz"])
        years = days.year.to_numpy()
        uy = np.arange(2020, 2027)
        year_idx = (years - 2020).astype(np.int64)
        exits = np.array(g["exits"], dtype=np.int64)
        for rs in g["starts"]:
            for ln in g["lens"]:
                re_ = rs + ln
                ok = exits > re_
                if not ok.any():
                    continue
                ex_used = exits[ok]
                pnl, dirs, width, ref = run_block(O, H, L, C, rs, re_, ex_used, TP_KIND, TP_VAL,
                                                  SL_KIND, SL_VAL, COST_PTS)
                usd = pnl.astype(np.float64) * PT_VALUE - COMMISSION
                nd = len(days)
                flat = usd.reshape(nd, -1)
                # filter masks per day
                wmed = pd.Series(width).rolling(20, min_periods=10).median().shift(1).to_numpy()
                wr = width / wmed
                rmean = pd.Series(ref).rolling(20, min_periods=10).mean().shift(1).to_numpy()
                trend = np.sign(ref - rmean)
                dir_masks = {"both": dirs != 0, "long": dirs == 1, "short": dirs == -1}
                trend_masks = {"none": np.ones(nd, bool), "with": (trend == dirs) & (dirs != 0)}
                width_masks = {"all": np.ones(nd, bool),
                               "skipwide": ~(wr > 1.5),
                               "skipnarrow": ~(wr < 0.7)}
                combos = [(a, b, c) for a in dir_masks for b in trend_masks for c in width_masks]
                nt, ns = len(TP_VAL), len(SL_VAL)
                ex_col = np.repeat(ex_used, nt * ns)
                tp_col = np.tile(np.repeat(np.arange(nt), ns), len(ex_used))
                sl_col = np.tile(np.arange(ns), len(ex_used) * nt)
                for a, b, c in combos:
                    m = dir_masks[a] & trend_masks[b] & width_masks[c]
                    ys, tr, wn, dd = stats_block(flat, m, year_idx, len(uy))
                    blk = pd.DataFrame({"anchor": anchor, "start": rs, "len": ln, "exit": ex_col,
                                        "tp": np.array(TP_LABEL)[tp_col],
                                        "sl": np.array(SL_LABEL)[sl_col],
                                        "dir": a, "trend": b, "width": c,
                                        "trades": tr, "wins": wn, "maxdd": dd})
                    for j, y in enumerate(uy):
                        blk[f"y{y}"] = ys[:, j]
                    rows.append(blk)
            print(f"{anchor} start {rs // 60:02d}:{rs % 60:02d} done, "
                  f"{time.time() - t0:.0f}s", flush=True)
    res = pd.concat(rows, ignore_index=True)
    for col in ["anchor", "tp", "sl", "dir", "trend", "width"]:
        res[col] = res[col].astype("category")
    res.to_parquet(out)
    print(f"saved {len(res):,} variants in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
