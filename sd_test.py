"""Supply & demand zones as filters / targets for the morning ORB (preset D neighbourhood).

Zone detection on 15-minute and 1-hour bars (built from the 1-minute series):
  impulse bar : body >= 1.5 x ATR14 and body >= 60% of its range
  base bar    : the bar before it, body <= 50% of its range
  demand zone : bullish impulse -> [base low, base high]; supply zone: bearish impulse.
A zone is usable from the impulse bar's close, for up to 20 days, until price closes through
its far edge (broken). "Fresh" = price has not traded back into it yet.

Tests (72 settings around D, judged per period against no filter):
  room-to-run  : skip if an opposing zone starts within X% ahead of the entry
  inside zone  : skip if the entry is inside an opposing zone
  origin       : only trade if a same-side zone sits within 0.5% behind the entry
  zone target  : take profit at the nearest opposing zone (36 settings, no-TP base)

Usage: python sd_test.py nq_1m.parquet
"""
import sys

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s
from ma_test import rec, summarise, STARTS, LENS, EXITS, TPK, TPV, SLK, SLV, D_KEY, YRS

pd.set_option("display.width", 250)
MAX_AGE = 20 * 1440


def make_bars(O, H, L, C, k):
    """Bars of k minutes on the flattened London-day grid. Returns abs close-minute index and OHLC."""
    o = O.ravel().reshape(-1, k); h = H.ravel().reshape(-1, k); l = L.ravel().reshape(-1, k); c = C.ravel().reshape(-1, k)
    valid = ~np.isnan(h).all(axis=1)
    with np.errstate(all="ignore"):
        bo = np.array([r[~np.isnan(r)][0] if v else np.nan for r, v in zip(o, valid)])
        bc = np.array([r[~np.isnan(r)][-1] if v else np.nan for r, v in zip(c, valid)])
        bh = np.nanmax(h, axis=1); bl = np.nanmin(l, axis=1)
    keep = valid & (bh > bl)
    t_close = (np.arange(len(o)) + 1) * k - 1
    return t_close[keep], bo[keep], bh[keep], bl[keep], bc[keep]


def detect_zones(t, o, h, l, c):
    tr = np.maximum(h - l, np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(l - np.r_[np.nan, c[:-1]]))
    atr = pd.Series(tr).rolling(14, min_periods=14).mean().shift(1).to_numpy()
    body = np.abs(c - o); rng = h - l
    imp = (body >= 1.5 * atr) & (body >= 0.6 * rng)
    base_ok = np.r_[False, (body[:-1] <= 0.5 * rng[:-1])]
    idx = np.where(imp & base_ok)[0]
    kind = np.where(c[idx] > o[idx], 1, -1)              # 1 demand, -1 supply
    zl = l[idx - 1]; zh = h[idx - 1]
    return t[idx], kind, zl, zh


@njit
def zone_life(created, kind, zl, zh, Hf, Lf, Cf, max_age):
    """First touch (price back into zone) and break (close through far edge) minute for each zone."""
    n = len(created)
    touch = np.full(n, 1 << 60); brk = np.full(n, 1 << 60)
    N = len(Hf)
    for i in range(n):
        end = min(created[i] + max_age, N - 1)
        for m in range(created[i] + 1, end):
            h = Hf[m]
            if h != h:
                continue
            if touch[i] == 1 << 60:
                if (kind[i] == 1 and Lf[m] <= zh[i]) or (kind[i] == -1 and h >= zl[i]):
                    touch[i] = m
            if (kind[i] == 1 and Cf[m] < zl[i]) or (kind[i] == -1 and Cf[m] > zh[i]):
                brk[i] = m
                break
    return touch, brk


@njit
def target_block(O, H, L, C, dirs, ents, pxs, tgt, ex, sl_pct, cost_pts):
    nd = O.shape[0]
    out = np.full(nd, np.nan)
    for d in range(nd):
        side = dirs[d]; ent = ents[d]
        if side == 0 or ent < 0 or ent >= ex:
            continue
        px = pxs[d]; sld = px * sl_pct / 100.0; tp = tgt[d]
        res = np.nan; lastc = px
        for m in range(ent, ex):
            h = H[d, m]
            if h != h:
                continue
            lastc = C[d, m]
            if side == 1:
                if L[d, m] <= px - sld:
                    res = -sld; break
                if tp == tp and m > ent and h >= tp:
                    res = tp - px; break
            else:
                if h >= px + sld:
                    res = -sld; break
                if tp == tp and m > ent and L[d, m] <= tp:
                    res = px - tp; break
        if res != res:
            res = (lastc - px) * side
        out[d] = res - cost_pts
    return out


def main():
    df = pd.read_parquet(sys.argv[1])
    days_all, O_all, H_all, L_all, C_all = s.day_matrix(df, "Europe/London")
    Hf, Lf, Cf = H_all.ravel(), L_all.ravel(), C_all.ravel()
    zones = {}
    for tf, k in [("15m", 15), ("1h", 60)]:
        t, o, h, l, c = make_bars(O_all, H_all, L_all, C_all, k)
        zc, zk, zl, zh = detect_zones(t, o, h, l, c)
        touch, brk = zone_life(zc.astype(np.int64), zk.astype(np.int64), zl, zh, Hf, Lf, Cf, MAX_AGE)
        zones[tf] = (zc, zk, zl, zh, touch, brk)
        print(f"{tf}: {len(zc):,} zones ({(zk == 1).sum():,} demand, {(zk == -1).sum():,} supply)")

    wk = np.where(days_all.weekday < 5)[0]
    days, O, H, L, C = days_all[wk], O_all[wk], H_all[wk], L_all[wk], C_all[wk]
    years = days.year.to_numpy()
    nd = len(days)

    def zone_feats(tf, dirs, ents, pxs, fresh_only):
        zc, zk, zl, zh, touch, brk = zones[tf]
        ahead = np.full(nd, np.inf); inside = np.zeros(nd, bool); behind = np.full(nd, np.inf)
        tgt = np.full(nd, np.nan)
        for d in range(nd):
            if dirs[d] == 0 or ents[d] < 0:
                continue
            tabs = wk[d] * 1440 + ents[d] - 1        # last completed minute before entry
            act = (zc <= tabs) & (brk > tabs) & (zc > tabs - MAX_AGE)
            if fresh_only:
                act &= touch > tabs
            px = pxs[d]; sd = dirs[d]
            opp = act & (zk == -sd); same = act & (zk == sd)
            if sd == 1:
                prox = zl[opp]                         # supply zone bottom
                inside[d] = ((zl[opp] <= px) & (zh[opp] >= px)).any()
                a = prox[prox > px]
                if len(a): ahead[d] = (a.min() - px) / px * 100; tgt[d] = a.min()
                b = zh[same][zh[same] <= px]
                if len(b): behind[d] = (px - b.max()) / px * 100
            else:
                prox = zh[opp]
                inside[d] = ((zl[opp] <= px) & (zh[opp] >= px)).any()
                a = prox[prox < px]
                if len(a): ahead[d] = (px - a.max()) / px * 100; tgt[d] = a.max()
                b = zl[same][zl[same] >= px]
                if len(b): behind[d] = (b.min() - px) / px * 100
        return ahead, inside, behind, tgt

    filt_rows, tgt_rows = [], []
    for rs in STARTS:
        for ln in LENS:
            re_ = rs + ln
            pnl, dirs, width, ref, ents, pxs = s.run_block_full(O, H, L, C, rs, re_, EXITS, TPK, TPV, SLK, SLV,
                                                                s.COST_PTS)
            usd = pnl.astype(float) * s.PT_VALUE - s.COMMISSION
            f = {}; targets = {}
            for tf in ("15m", "1h"):
                for fresh in (False, True):
                    tag = f"{tf}{' fresh' if fresh else ''}"
                    ahead, inside, behind, tgt = zone_feats(tf, dirs, ents, pxs, fresh)
                    for x in (0.25, 0.5, 1.0):
                        f[f"skip if {tag} opposing zone within {x}%"] = ~(ahead < x)
                    f[f"skip if entry inside {tag} opposing zone"] = ~inside
                    f[f"only if {tag} same-side zone within 0.5% behind"] = behind < 0.5
                    targets[f"TP at nearest {tag} opposing zone"] = tgt
                    t2 = tgt.copy(); t2[ahead < 0.5] = np.nan
                    targets[f"TP at nearest {tag} opposing zone if >=0.5% away"] = t2
            for ei, ex in enumerate(EXITS):
                for ti in range(len(TPV)):
                    for si in range(len(SLV)):
                        base = usd[:, ei, ti, si]
                        traded = ~np.isnan(base)
                        key = (rs, ln, int(ex), TPV[ti], SLV[si])
                        filt_rows.append(rec(key, "(none)", base, traded, years))
                        for name, m in f.items():
                            filt_rows.append(rec(key, name, base, traded & m, years))
                for si in range(len(SLV)):
                    key = (rs, ln, int(ex), 99.0, SLV[si])
                    base = usd[:, ei, 1, si]
                    tgt_rows.append(rec(key, "(none)", base, ~np.isnan(base), years))
                    for name, tg in targets.items():
                        p = target_block(O, H, L, C, dirs, ents, pxs, tg, int(ex), SLV[si], s.COST_PTS)
                        v = p * s.PT_VALUE - s.COMMISSION
                        tgt_rows.append(rec(key, name, v, ~np.isnan(v), years))
        print(f"start {rs // 60:02d}:{rs % 60:02d} done", flush=True)

    print("\n===== Zones as filters (72 settings around D) =====")
    fr = summarise(filt_rows)
    print("\n===== Zones as take-profit targets (36 settings, vs no take-profit) =====")
    tr = summarise(tgt_rows)
    for name, r in [("filters", fr), ("targets", tr)]:
        d = r[r.setting == D_KEY].sort_values("ret_dd", ascending=False).head(6)
        print(f"\nPreset D itself, best {name} by return/drawdown:")
        print(d[["test", "trades", "maxdd", "total", "ret_dd"] + YRS].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
