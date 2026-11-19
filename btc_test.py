"""Presets D/E on BTCUSD with percentage fees, compared with NQ in the same units (% of position).

Results are per trade as % of position size, summed, and in $ for a fixed $50,000 position.
Weekdays only, London clock, same rules as the NQ backtest.

Usage: python btc_test.py btc_1m.parquet nq_1m.parquet
"""
import sys

import numpy as np
import pandas as pd

import orb_sweep as s
from extra_test import gen_block

pd.set_option("display.width", 250)
YRS = list(range(2020, 2027))
PERIODS = {"2020-23": range(2020, 2024), "2024-25": range(2024, 2026), "2026": [2026]}
NOTIONAL = 50_000


def load(path):
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.weekday < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    return days, O, H, L, C, atr


def pct_series(mk, rs, ln, ex, stop, mult, fee_pct):
    days, O, H, L, C, atr = mk
    sp = mult * atr if stop == "atr" else np.full(len(days), np.nan)
    slp = mult if stop == "pct" else 1.0
    p = gen_block(O, H, L, C, rs, rs + ln, ex, 0.0, 0, sp, slp, 0.0, 0, 0.0)   # points, no cost
    ref = C[:, rs + ln - 1]
    if isinstance(fee_pct, tuple):   # futures: (slippage pts round trip, commission $, $ per point), per trade
        slip, comm, ptv = fee_pct
        fee = (slip + comm / ptv) / ref * 100
    else:
        fee = fee_pct
    r = p / ref * 100 - fee
    return pd.Series(r, index=days).dropna()


def summary(r):
    usd = r / 100 * NOTIONAL
    eq = usd.cumsum(); yr = usd.groupby(usd.index.year).sum()
    return {**{str(y): round(yr.get(y, 0)) for y in YRS}, "Total $": round(usd.sum()),
            "MaxDD $": round((eq.cummax() - eq).max()), "Win%": round((r > 0).mean() * 100),
            "Avg trade %": round(r.mean(), 3), "Trades": len(r), "PosYrs": f"{(yr > 0).sum()}/{len(yr)}"}


def main():
    btc = load(sys.argv[1]); nq = load(sys.argv[2])
    nq_fee = (1.0, 1.24, 2.0)        # MNQ: 1 pt slippage, $1.24 commission, $2/pt
    markets = [("NQ", nq, nq_fee), ("BTC fee 0.05%", btc, 0.05), ("BTC fee 0.12%", btc, 0.12)]
    if len(sys.argv) > 3:
        gold = load(sys.argv[3])
        markets.append(("Gold (MGC)", gold, (0.2, 1.24, 10.0)))   # 1 tick each side, $10/pt
    out = {}
    for name, mk, fee in markets:
        for pname, stop, mult in [("D 1% stop", "pct", 1.0), ("E 1xATR stop", "atr", 1.0)]:
            out[f"{name} | {pname}"] = summary(pct_series(mk, 450, 60, 1255, stop, mult, fee))
    print(f"===== Presets D/E (07:30-08:30 London, no TP, exit 20:55) on a ${NOTIONAL:,} position =====")
    print("(Futures costs: MNQ 1 pt + $1.24, MGC 0.2 pt + $1.24 per round trip, converted to % per trade)")
    print(pd.DataFrame(out).to_string())

    rows = []
    for name, mk, fee in markets:
        for rs in (435, 450, 465):
            for ln in (45, 60, 90):
                for ex in (1170, 1255):
                    for sname, stop, mult in [("1% stop", "pct", 1.0), ("2% stop", "pct", 2.0),
                                              ("0.8x ATR", "atr", 0.8), ("1x ATR", "atr", 1.0),
                                              ("1.5x ATR", "atr", 1.5)]:
                        r = pct_series(mk, rs, ln, ex, stop, mult, fee) / 100 * NOTIONAL
                        yr = r.groupby(r.index.year).sum()
                        rec = {"market": name, "stop": sname, "total": r.sum()}
                        for p, ys in PERIODS.items():
                            rec[p] = sum(yr.get(y, 0) for y in ys)
                        rows.append(rec)
    r = pd.DataFrame(rows)
    g = r.groupby(["market", "stop"], sort=False)
    summ = pd.DataFrame({"mean total $": g.total.mean().round(0),
                         **{f"{p} mean $": g[p].mean().round(0) for p in PERIODS},
                         **{f"{p} %>0": (g[p].apply(lambda x: (x > 0).mean()) * 100).round(0) for p in PERIODS}})
    print(f"\n===== 18 nearby settings (start 07:15-07:45, range 45-90 min, exit 19:30/20:55), ${NOTIONAL:,} position =====")
    print(summ.to_string())


if __name__ == "__main__":
    main()
