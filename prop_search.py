"""Search for a prop-firm-friendly ORB variant: steady daily P&L rather than big total profit.

Take-profit and stop are multiples of the 14-day average daily range (ATR14), so they adapt to volatility.
Windows: London morning (London clock) and the US open (New York clock).
Scored on 2020-2023 only:
  sharpe   = mean / std of daily P&L x sqrt(252)   (days with no trade count as 0)
  pos_mo   = share of positive months
  top10    = share of total profit from the 10 best days (lower = less outlier-dependent)
Then checked on 2024-2025 and 2026.

Usage: python prop_search.py   -> prop_search.parquet
"""
import time

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s

PTV, COST, COMM = 2.0, 1.0, 1.24
TPM = np.array([0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 99.0])
SLM = np.array([0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0])
GRIDS = {
    "London": ("Europe/London", list(range(420, 511, 15)), [15, 30, 45, 60],
               [630, 720, 865, 960, 1255]),            # 10:30, 12:00, 14:25, 16:00, 20:55
    "NewYork": ("America/New_York", [570, 585, 600], [5, 15, 30, 45, 60],
                [660, 720, 780, 900, 955]),             # 11:00, 12:00, 13:00, 15:00, 15:55
}


@njit
def block(O, H, L, C, rs, re_, exits, atr, tpm, slm, cost):
    nd = O.shape[0]
    ne, nt, ns = len(exits), len(tpm), len(slm)
    pnl = np.full((nd, ne, nt, ns), np.nan, dtype=np.float32)
    mae = np.full((nd, ne, nt, ns), np.nan, dtype=np.float32)
    cmax = np.empty(1440); cmin = np.empty(1440); lastc = np.empty(1440)
    mx = exits.max()
    for d in range(nd):
        a = atr[d]
        if a != a:
            continue
        rh = -1e18; rl = 1e18; nbar = 0; nflat = 0
        for m in range(rs, re_):
            h = H[d, m]
            if h == h:
                nbar += 1
                if h > rh: rh = h
                if L[d, m] < rl: rl = L[d, m]
                if h == L[d, m]: nflat += 1
        if nbar < (re_ - rs) * 0.8 or nflat > nbar * 0.5 or rh <= rl:
            continue
        side = 0; ent = -1; px = 0.0
        for m in range(re_, mx):
            h = H[d, m]
            if h != h:
                continue
            o = O[d, m]; up = h >= rh; dn = L[d, m] <= rl
            if up or dn:
                if o >= rh: side = 1; px = o
                elif o <= rl: side = -1; px = o
                elif up and dn:
                    if rh - o <= o - rl: side = 1; px = rh
                    else: side = -1; px = rl
                elif up: side = 1; px = rh
                else: side = -1; px = rl
                ent = m
                break
        if ent < 0:
            continue
        fav = -1e18; adv = 1e18; lc = px
        for m in range(ent, mx):
            h = H[d, m]
            if h == h:
                if side == 1:
                    f = h - px; ad = L[d, m] - px
                else:
                    f = px - L[d, m]; ad = px - h
                if f > fav: fav = f
                if ad < adv: adv = ad
                lc = (C[d, m] - px) * side
            cmax[m] = fav; cmin[m] = adv; lastc[m] = lc
        for ei in range(ne):
            ex = exits[ei]
            if ex <= ent:
                continue
            for ti in range(nt):
                tpd = tpm[ti] * a
                lo = ent; hi = ex
                while lo < hi:
                    mid = (lo + hi) // 2
                    if cmax[mid] >= tpd: hi = mid
                    else: lo = mid + 1
                th = lo
                for si in range(ns):
                    sld = slm[si] * a
                    lo = ent; hi = ex
                    while lo < hi:
                        mid = (lo + hi) // 2
                        if cmin[mid] <= -sld: hi = mid
                        else: lo = mid + 1
                    sh = lo
                    if sh < ex and sh <= th:
                        r = -sld; wa = -sld
                    elif th < ex:
                        r = tpd; wa = cmin[th] if cmin[th] > -sld else -sld
                    else:
                        r = lastc[ex - 1]; wa = cmin[ex - 1]
                    pnl[d, ei, ti, si] = r - cost
                    mae[d, ei, ti, si] = wa - cost
    return pnl, mae


def stats(v, years, months):
    """v: [day, k] $ per MNQ with NaN = no trade. Returns dict of arrays over k."""
    x = np.nan_to_num(v)
    out = {}
    for name, mask in [("IS", years <= 2023), ("VAL", (years >= 2024) & (years <= 2025)), ("HOLD", years == 2026)]:
        xm = x[mask]
        out[f"{name}_tot"] = xm.sum(axis=0)
        sd = xm.std(axis=0)
        out[f"{name}_sharpe"] = np.where(sd > 0, xm.mean(axis=0) / np.where(sd > 0, sd, 1) * np.sqrt(252), 0)
        mo = pd.DataFrame(xm).groupby(months[mask]).sum().to_numpy()
        out[f"{name}_posmo"] = (mo > 0).mean(axis=0)
    xi = x[years <= 2023]
    srt = -np.sort(-xi, axis=0)
    tot = xi.sum(axis=0)
    out["IS_top10"] = np.where(tot > 0, srt[:10].sum(axis=0) / np.where(tot > 0, tot, 1), 9.9)
    eq = np.cumsum(x, axis=0)
    out["maxdd"] = (np.maximum.accumulate(eq, axis=0) - eq).max(axis=0)
    eqi = np.cumsum(xi, axis=0)
    out["IS_maxdd"] = (np.maximum.accumulate(eqi, axis=0) - eqi).max(axis=0)
    out["trades"] = (~np.isnan(v)).sum(axis=0)
    out["winrate"] = (v > 0).sum(axis=0) / np.maximum(out["trades"], 1)
    out["worst_day"] = x.min(axis=0)
    return out


def main():
    df = pd.read_parquet("nq_1m.parquet")
    t0 = time.time()
    frames = []
    for anchor, (tz, starts, lens, exits) in GRIDS.items():
        days, O, H, L, C = s.day_matrix(df, tz)
        wk = days.weekday < 5
        days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
        rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
        atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
        years = days.year.to_numpy(); months = (days.year * 100 + days.month).to_numpy()
        for rs in starts:
            for ln in lens:
                ex_ok = np.array([e for e in exits if e > rs + ln + 15], dtype=np.int64)
                p, mae = block(O, H, L, C, rs, rs + ln, ex_ok, atr, TPM, SLM, COST)
                usd = p.astype(float) * PTV - COMM
                flat = usd.reshape(len(days), -1)
                st = stats(flat, years, months)
                ne, nt, ns = len(ex_ok), len(TPM), len(SLM)
                blk = pd.DataFrame({"anchor": anchor, "start": rs, "len": ln,
                                    "exit": np.repeat(ex_ok, nt * ns),
                                    "tp": np.tile(np.repeat(TPM, ns), ne), "sl": np.tile(SLM, ne * nt)})
                for k, v in st.items():
                    blk[k] = v
                blk["worst_open"] = np.nanmin(mae.reshape(len(days), -1).astype(float) * PTV - COMM, axis=0)
                frames.append(blk)
            print(f"{anchor} {rs // 60:02d}:{rs % 60:02d} done {time.time() - t0:.0f}s", flush=True)
    r = pd.concat(frames, ignore_index=True)
    r.to_parquet("prop_search.parquet")
    print(f"saved {len(r):,} variants")


if __name__ == "__main__":
    main()
