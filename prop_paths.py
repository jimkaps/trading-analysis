"""Per-day trade path for presets D and E: closed P&L plus worst and best open P&L during the trade.
Needed to simulate prop-firm drawdowns that are checked intraday.

Output: prop_days.parquet with columns per preset: pnl, mae, mfe ($ per 1 MNQ, after costs).
"""
import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s

PTV, COST, COMM = 2.0, 1.0, 1.24


@njit
def path_block(O, H, L, C, rs, re_, ex, stop_pts, sl_pct, cost_pts):
    nd = O.shape[0]
    pnl = np.full(nd, np.nan); mae = np.full(nd, np.nan); mfe = np.full(nd, np.nan)
    for d in range(nd):
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
        for m in range(re_, ex):
            h = H[d, m]
            if h != h:
                continue
            o = O[d, m]; a = h >= rh; b = L[d, m] <= rl
            if a or b:
                if o >= rh: side = 1; px = o
                elif o <= rl: side = -1; px = o
                elif a and b:
                    if rh - o <= o - rl: side = 1; px = rh
                    else: side = -1; px = rl
                elif a: side = 1; px = rh
                else: side = -1; px = rl
                ent = m
                break
        if ent < 0:
            continue
        sp = stop_pts[d]
        sld = sp if sp == sp else px * sl_pct / 100.0
        worst = 0.0; best = 0.0; res = np.nan; lastc = px
        for m in range(ent, ex):
            h = H[d, m]
            if h != h:
                continue
            lo = L[d, m]; lastc = C[d, m]
            fav = (h - px) if side == 1 else (px - lo)
            adv = (lo - px) if side == 1 else (px - h)
            if adv <= -sld:
                worst = -sld; res = -sld; break
            if adv < worst: worst = adv
            if fav > best: best = fav
        if res != res:
            res = (lastc - px) * side
        pnl[d] = res - cost_pts
        mae[d] = worst - cost_pts
        mfe[d] = best
    return pnl, mae, mfe


def main():
    df = pd.read_parquet("nq_1m.parquet")
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    out = pd.DataFrame(index=days)
    for name, sp, slp in [("D", np.full(len(days), np.nan), 1.0), ("E", atr, 1.0)]:
        p, a, f = path_block(O, H, L, C, 450, 510, 1255, sp, slp, COST)
        out[f"{name}_pnl"] = p * PTV - COMM
        out[f"{name}_mae"] = a * PTV - COMM
        out[f"{name}_mfe"] = f * PTV
    out = out.dropna(how="all")
    out.to_parquet("prop_days.parquet")
    for n in "DE":
        v = out[f"{n}_pnl"].dropna()
        print(f"{n}: total ${v.sum():,.0f}, trades {len(v)}, worst day ${v.min():,.0f}, best day ${v.max():,.0f}, "
              f"median loss ${v[v < 0].median():,.0f}, median win ${v[v > 0].median():,.0f}, "
              f"worst intraday open loss ${out[f'{n}_mae'].min():,.0f}")


if __name__ == "__main__":
    main()
