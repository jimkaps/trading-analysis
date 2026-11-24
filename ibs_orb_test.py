"""Can ORB preset E run alongside the "IBS long (partner TEST)" strategy? Correlation, overlap and combined risk.

IBS long, as in the TradingView script (saved as "IBS long (partner TEST)"):
  * CME session bars: 18:00 ET to 17:00 ET (dated by the day they end).
  * Signal: the previous session's IBS = (close - low) / (high - low) < 0.2.
  * Entry: long at the 18:05 ET open (the 5-minute script fills at the open of the bar after the session's first bar).
  * Stop: 0.75 x ATR14 (simple average of the session bars' true range, known at the previous close) below the fill.
  * Exit: 16:45 ET (close of the 16:40 5-minute bar) or the stop.
ORB preset E: futures_test.daily_pnl, unchanged (range 07:30-08:30 London, stop 1 x 14-day range, flat 15:55 ET).
Both on 1 MNQ ($2/pt) with the same costs: 1 pt slippage round trip + $1.24 commission.

Usage: python ibs_orb_test.py nq_1m_2012_2026.parquet
"""
import sys

import numpy as np
import pandas as pd

import futures_test as f
import orb_sweep as s

PTV, COST_PTS, COMM = 2.0, 1.0, 1.24
PERIODS = {"2013-19": (2013, 2019), "2020-23": (2020, 2023), "2024-26": (2024, 2026)}


def session_frame(path):
    df = pd.read_parquet(path).tz_convert("America/New_York")
    t = df.index
    mins = t.hour * 60 + t.minute
    df = df[(mins < 17 * 60) | (mins >= 18 * 60)]              # CME daily break 17:00-18:00 ET
    t = df.index
    sess = (t + pd.Timedelta(hours=6)).normalize().tz_localize(None)   # 18:00 ET belongs to the next day's session
    df = df.assign(sess=sess, m=((t.hour * 60 + t.minute + 360) % 1440))  # minutes since 18:00 ET
    df = df[pd.DatetimeIndex(df.sess).day_of_week < 5]
    return df


def ibs_trades(df, ibs_max=0.2, stop_atr=0.75, entry_m=5, exit_m=22 * 60 + 45):
    g = df.groupby("sess")
    bars = pd.DataFrame({"o": g.open.first(), "h": g.high.max(), "l": g.low.min(), "c": g.close.last(), "n": g.size()})
    bars = bars[bars.n > 600]                                     # skip holiday stubs
    pc = bars.c.shift(1)
    tr = np.maximum(bars.h, pc) - np.minimum(bars.l, pc)
    atr = tr.rolling(14).mean().shift(1)
    ibs = ((bars.c - bars.l) / (bars.h - bars.l)).shift(1)
    rows = []
    for d, grp in df.groupby("sess"):
        if d not in bars.index or not (ibs.get(d, np.nan) < ibs_max) or np.isnan(atr.get(d, np.nan)):
            continue
        x = grp[(grp.m >= entry_m) & (grp.m < exit_m)]
        if x.empty:
            continue
        ent = x.open.iloc[0] + COST_PTS / 2
        stop = ent - stop_atr * atr[d]
        hit = np.where(x.low.to_numpy() <= stop)[0]
        if len(hit):
            k = hit[0]
            px = min(stop, x.open.iloc[k]) if k > 0 else stop
            ext, why = px - COST_PTS / 2, "stop"
            xt = x.index[k]
        else:
            ext, why, xt = x.close.iloc[-1] - COST_PTS / 2, "time", x.index[-1]
        rows.append({"date": d, "entry_t": x.index[0], "exit_t": xt, "pnl": (ext - ent) * PTV - COMM, "why": why})
    return pd.DataFrame(rows).set_index("date")


def orb_direction(path):
    """Direction and entry/exit time (ET) of the ORB E trade each day, same rules as gen_block (first break wins)."""
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    out = {}
    for i, d in enumerate(days):
        rh, rl = np.nanmax(H[i, 450:510]), np.nanmin(L[i, 450:510])
        if not np.isfinite(rh):
            continue
        ny_exit = (pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)).tz_convert("Europe/London")
        ex = ny_exit.hour * 60 + ny_exit.minute
        up = np.where(H[i, 510:ex] > rh)[0]; dn = np.where(L[i, 510:ex] < rl)[0]
        if len(up) == 0 and len(dn) == 0:
            continue
        u = up[0] if len(up) else 10**6; w = dn[0] if len(dn) else 10**6
        out[d] = 1 if u < w else -1
    return pd.Series(out)


def stats(v):
    eq = v.cumsum()
    return {"net $": round(v.sum()), "max DD $": round((eq.cummax() - eq).max()),
            "worst day $": round(v.min()), "days traded": int((v != 0).sum())}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    df = session_frame(path)
    ibs = ibs_trades(df)
    orb, _ = f.daily_pnl(path)
    orb.index = orb.index.tz_localize(None) if orb.index.tz else orb.index
    odir = orb_direction(path)

    start, end = orb.index.min(), orb.index.max()
    ibs = ibs[(ibs.index >= start) & (ibs.index <= end)]
    cal = pd.bdate_range(start, end)
    P = pd.DataFrame({"ORB": orb.reindex(cal).fillna(0), "IBS": ibs.pnl.groupby(level=0).sum().reindex(cal).fillna(0)})
    P["Both"] = P.ORB + P.IBS

    pd.set_option("display.width", 220)
    print(f"Data {start.date()} -> {end.date()}; IBS trades {len(ibs)} ({(ibs.why == 'stop').mean():.0%} stopped), ORB trades {int((P.ORB != 0).sum())}")

    print("\n===== Each alone and together (1 MNQ each) =====")
    tbl = {}
    for name in ["ORB", "IBS", "Both"]:
        row = stats(P[name])
        for p, (a, b) in PERIODS.items():
            row[p] = round(P[name][(P.index.year >= a) & (P.index.year <= b)].sum())
        tbl[name] = row
    print(pd.DataFrame(tbl).to_string())

    print("\n===== Correlation of daily P&L =====")
    both_days = (P.ORB != 0) & (P.IBS != 0)
    for p, (a, b) in {"all": (2013, 2026), **PERIODS}.items():
        m = (P.index.year >= a) & (P.index.year <= b)
        wk = P[m].resample("W").sum(); mo = P[m].resample("ME").sum()
        print(f"{p:8s} daily {P[m].ORB.corr(P[m].IBS):+.2f} | days both trade {P[m & both_days].ORB.corr(P[m & both_days].IBS):+.2f} "
              f"| weekly {wk.ORB.corr(wk.IBS):+.2f} | monthly {mo.ORB.corr(mo.IBS):+.2f}")

    print("\n===== Overlap on the same instrument =====")
    on = ibs.index.intersection(odir.index)
    print(f"IBS days {len(ibs)}; ORB also trades on {len(on)} of them ({len(on)/len(ibs):.0%})")
    opp = (odir.loc[on] == -1)
    print(f"ORB is SHORT while IBS is long on {opp.sum()} days ({opp.mean():.0%} of overlap days); "
          f"same direction (long) on {(~opp).sum()} days")
    lost = P.loc[on]
    print(f"On overlap days: ORB {lost.ORB.sum():,.0f}, IBS {lost.IBS.sum():,.0f}; "
          f"when ORB short: ORB {lost.ORB[opp.values].sum():,.0f}, IBS {lost.IBS[opp.values].sum():,.0f}")

    print("\n===== Bad days =====")
    worst = P.Both.nsmallest(10).index
    print(f"ORB's 10 worst days: IBS made {P.IBS.loc[P.ORB.nsmallest(10).index].sum():,.0f} on them")
    print(f"IBS's 10 worst days: ORB made {P.ORB.loc[P.IBS.nsmallest(10).index].sum():,.0f} on them")
    m20 = P.index.year >= 2020
    print("2020-26 drawdown: ORB {:,.0f}, IBS {:,.0f}, both {:,.0f}".format(
        *[(lambda e: (e.cummax() - e).max())(P[c][m20].cumsum()) for c in ["ORB", "IBS", "Both"]]))

    yr = P.groupby(P.index.year).sum().round(0)
    print("\nBy year:\n" + yr.to_string())
    P.to_csv("ibs_orb_daily.csv")


if __name__ == "__main__":
    main()
