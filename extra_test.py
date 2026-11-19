"""Trade-management ideas for the morning ORB, judged on 36 settings around preset D
(start 07:15/07:30/07:45, range 45/60/90, exit 19:30/20:55, stop 0.75%/1%, no take-profit).

Families:
  break-even stop  : move stop to entry once trade is +X% in profit
  reverse          : after a stop-out, (1) reverse at the stop price, or (2) re-enter on the opposite range break
  entry confirm    : stop entry with a buffer beyond the range, or enter on a 5-minute close beyond it
  ATR stop         : stop = k x daily ATR14 instead of a % of price
  partial profit   : half off at +1/1.5/2%, half runs to the exit time
  later exit       : hold until 21:55 / 23:00 / 23:59 London instead of 20:55
  vol sizing       : contracts scaled by (100-day avg daily range / 14-day avg), capped 0.5x-2x

Usage: python extra_test.py nq_1m.parquet
"""
import sys

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s
from ma_test import rec, summarise, STARTS, LENS, YRS

pd.set_option("display.width", 250)
EXITS = [1170, 1255]
SLS = [0.75, 1.0]
D_KEY = (450, 60, 1255, 99.0, 1.0)


@njit
def manage(O, H, L, C, d, side, ent, px, ex, sl_pct, stop_pts, be_trig, start_incl):
    """Manage one position. Returns (pnl_pts_before_costs, exit_minute, stopped_flag, stop_price)."""
    sld = stop_pts if stop_pts == stop_pts else px * sl_pct / 100.0
    stop = px - sld if side == 1 else px + sld
    be_on = False
    lastc = px
    m0 = ent if start_incl else ent + 1
    for m in range(m0, ex):
        h = H[d, m]
        if h != h:
            continue
        lo = L[d, m]
        lastc = C[d, m]
        if side == 1:
            if lo <= stop:
                return stop - px, m, True, stop
            if be_trig > 0 and not be_on and h >= px * (1 + be_trig / 100.0):
                be_on = True; stop = max(stop, px + 0.5)       # entry + a little to cover costs
        else:
            if h >= stop:
                return px - stop, m, True, stop
            if be_trig > 0 and not be_on and lo <= px * (1 - be_trig / 100.0):
                be_on = True; stop = min(stop, px - 0.5)
    return (lastc - px) * side, ex, False, stop


@njit
def gen_block(O, H, L, C, rs, re_, ex, buf, confirm, stop_pts, sl_pct, be_trig, rev_mode, cost_pts):
    nd = O.shape[0]
    out = np.full(nd, np.nan)
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
        up = rh * (1 + buf / 100.0); dn = rl * (1 - buf / 100.0)
        side = 0; ent = -1; px = 0.0; incl = True
        for m in range(re_, ex):
            h = H[d, m]
            if h != h:
                continue
            if confirm == 0:
                o = O[d, m]; a = h >= up; b = L[d, m] <= dn
                if a or b:
                    if o >= up: side = 1; px = o
                    elif o <= dn: side = -1; px = o
                    elif a and b:
                        if up - o <= o - dn: side = 1; px = up
                        else: side = -1; px = dn
                    elif a: side = 1; px = up
                    else: side = -1; px = dn
                    ent = m; incl = True
                    break
            else:
                if (m + 1) % 5 == 0:
                    c = C[d, m]
                    if c > up: side = 1; px = c; ent = m; incl = False; break
                    if c < dn: side = -1; px = c; ent = m; incl = False; break
        if ent < 0:
            continue
        sp = stop_pts[d]
        r1, xm, stopped, stop_px = manage(O, H, L, C, d, side, ent, px, ex, sl_pct, sp, be_trig, incl)
        total = r1 - cost_pts
        if stopped and rev_mode > 0 and xm < ex - 1 and r1 < 0:
            side2 = -side
            if rev_mode == 1:
                r2, _, _, _ = manage(O, H, L, C, d, side2, xm, stop_px, ex, sl_pct, sp, be_trig, False)
                total += r2 - cost_pts
            else:
                lvl = rl if side == 1 else rh
                for m in range(xm + 1, ex):
                    h = H[d, m]
                    if h != h:
                        continue
                    hit = (side2 == -1 and L[d, m] <= lvl) or (side2 == 1 and h >= lvl)
                    if hit:
                        o = O[d, m]
                        p2 = lvl
                        if side2 == -1 and o < lvl: p2 = o
                        if side2 == 1 and o > lvl: p2 = o
                        r2, _, _, _ = manage(O, H, L, C, d, side2, m, p2, ex, sl_pct, sp, be_trig, True)
                        total += r2 - cost_pts
                        break
        out[d] = total
    return out


def main():
    df = pd.read_parquet(sys.argv[1])
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    years = days.year.to_numpy()
    nd = len(days)
    day_rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr14 = pd.Series(day_rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    atr100 = pd.Series(day_rng).rolling(100, min_periods=50).mean().shift(1).to_numpy()
    size = np.clip(atr100 / atr14, 0.5, 2.0); size = np.where(np.isnan(size), 1.0, size)
    nanstop = np.full(nd, np.nan)

    fam = {k: [] for k in ["break-even", "reverse", "entry confirm", "ATR stop", "partial profit",
                           "later exit", "vol sizing"]}
    usd = lambda p: p * s.PT_VALUE - s.COMMISSION
    for rs in STARTS:
        for ln in LENS:
            re_ = rs + ln
            # baseline + partials + later exits from the standard engine
            pnl, *_ = s.run_block_full(O, H, L, C, rs, re_, np.array([1170, 1255, 1315, 1380, 1439]),
                                       np.array([0, 0, 0, 0]), np.array([1.0, 1.5, 2.0, 99.0]),
                                       np.array([0, 0]), np.array(SLS), s.COST_PTS)
            P = pnl.astype(float) * s.PT_VALUE - s.COMMISSION
            for ei, ex in enumerate(EXITS):
                for si, sl in enumerate(SLS):
                    key = (rs, ln, ex, 99.0, sl)
                    base = P[:, ei, 3, si]; tr = ~np.isnan(base)
                    for k in fam:
                        fam[k].append(rec(key, "(none)", base, tr, years))
                    # partial profit: average of target leg and runner leg (commission per leg halves)
                    for ti, t in enumerate([1.0, 1.5, 2.0]):
                        v = 0.5 * P[:, ei, ti, si] + 0.5 * base
                        fam["partial profit"].append(rec(key, f"half off at +{t}%, half runs", v, tr, years))
                    if ex == 1255:
                        for xi, (xx, lab) in enumerate([(1315, "21:55"), (1380, "23:00"), (1439, "23:59")]):
                            v = P[:, 2 + xi, 3, si]
                            fam["later exit"].append(rec(key, f"exit {lab} instead of 20:55", v, ~np.isnan(v), years))
                    v = base * size
                    fam["vol sizing"].append(rec(key, "size x (ATR100/ATR14), 0.5-2x", v, tr, years))
                    v = base / size
                    fam["vol sizing"].append(rec(key, "inverse: size x (ATR14/ATR100)", v, tr, years))

                    def run(name, family, **kw):
                        args = dict(buf=0.0, confirm=0, stop_pts=nanstop, be_trig=0.0, rev_mode=0)
                        args.update(kw)
                        p = gen_block(O, H, L, C, rs, re_, ex, args["buf"], args["confirm"], args["stop_pts"], sl,
                                      args["be_trig"], args["rev_mode"], s.COST_PTS)
                        v = np.where(np.isnan(p), np.nan, p * s.PT_VALUE - s.COMMISSION * np.where(
                            args["rev_mode"] > 0, 1.0, 1.0))
                        fam[family].append(rec(key, name, v, ~np.isnan(v), years))
                    for be in (0.5, 1.0, 1.5):
                        run(f"break-even after +{be}%", "break-even", be_trig=be)
                    run("stop-and-reverse at stop price", "reverse", rev_mode=1)
                    run("re-enter on opposite range break", "reverse", rev_mode=2)
                    for b in (0.05, 0.1, 0.2):
                        run(f"entry buffer {b}% beyond range", "entry confirm", buf=b)
                    run("enter on 5-min close beyond range", "entry confirm", confirm=1)
                    run("enter on 5-min close beyond range +0.05%", "entry confirm", confirm=1, buf=0.05)
                    if sl == 1.0:
                        for k_ in (0.3, 0.45, 0.6, 0.8):
                            run(f"stop = {k_} x ATR14", "ATR stop", stop_pts=k_ * atr14)
        print(f"start {rs // 60:02d}:{rs % 60:02d} done", flush=True)

    res = {}
    for k, rows in fam.items():
        print(f"\n===== {k} =====")
        res[k] = summarise(rows)
    allr = pd.concat(res.values())
    d = allr[(allr.setting == D_KEY)].drop_duplicates("test").sort_values("ret_dd", ascending=False)
    print("\nPreset D itself, all ideas ranked by return/drawdown:")
    print(d[["test", "trades", "maxdd", "total", "ret_dd"] + YRS].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
