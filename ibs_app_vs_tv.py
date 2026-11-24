"""The phone app's IBS rule vs the TradingView "IBS long (partner TEST)" rule, on the same 1-minute NQ data.

App rule (android_app core/Market.kt + Engine.kt, branch claude/sharp-franklin-o9bmsa of android_kernel_samsung_crespo):
  * Daily bars from the cash session, 09:30-16:00 ET (the app reads QQQ).
  * Buy at the 16:00 ET close if (IBS today < 0.3 and IBS yesterday < 0.3) or IBS today < 0.1 or RSI(2) < 10,
    except on Fridays. Hold to the next session's close; if the signal fires again that day, keep holding.
    No stop, no target.
TradingView rule: ibs_orb_test.ibs_trades (CME session IBS < 0.2, buy 18:05 ET, stop 0.75 x ATR14, flat 16:45 ET).
Both on 1 MNQ ($2/pt), 1 pt slippage round trip + $1.24 commission. The app's CFD financing (~6.5%/yr) is not
included; on MNQ futures that cost is inside the price.

Usage: python ibs_app_vs_tv.py nq_1m_2012_2026.parquet
"""
import sys

import numpy as np
import pandas as pd

import ibs_orb_test as t

PTV, COST_PTS, COMM = 2.0, 1.0, 1.24


def cash_bars(path):
    df = pd.read_parquet(path).tz_convert("America/New_York")
    m = df.index.hour * 60 + df.index.minute
    rth = df[(m >= 570) & (m < 960)]
    rth = rth[rth.index.day_of_week < 5]
    g = rth.groupby(rth.index.normalize().tz_localize(None))
    b = pd.DataFrame({"h": g.high.max(), "l": g.low.min(), "c": g.close.last(), "n": g.size()})
    return b[b.n > 300]                                            # skip half days with missing data


def rsi2(c):
    ch = c.diff()
    up = ch.clip(lower=0).ewm(alpha=0.5, adjust=True).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=0.5, adjust=True).mean()
    return 100 - 100 / (1 + up / dn)


def app_trades(b):
    ibs = ((b.c - b.l) / (b.h - b.l)).where(b.h > b.l, 0.5)
    sig = (((ibs < 0.3) & (ibs.shift(1) < 0.3)) | (ibs < 0.1) | (rsi2(b.c) < 10)) & (b.index.day_of_week != 4)
    rows, i, idx, C = [], 0, b.index, b.c.to_numpy()
    s = sig.to_numpy()
    while i < len(b) - 1:
        if not s[i]:
            i += 1; continue
        j = i + 1
        while j < len(b) - 1 and s[j]:
            j += 1
        rows.append({"entry": idx[i], "date": idx[j], "days": j - i, "pnl": (C[j] - C[i] - COST_PTS) * PTV - COMM})
        i = j + 1 if not s[j] else j
    return pd.DataFrame(rows).set_index("date")


def stats(v, yrs):
    eq = v.cumsum()
    return {"trades": len(v), "win %": round((v > 0).mean() * 100), "$/trade": round(v.mean(), 1),
            "net $": round(v.sum()), "$/yr": round(v.sum() / yrs), "max DD $": round((eq.cummax() - eq).max()),
            "worst trade $": round(v.min())}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    b = cash_bars(path)
    app = app_trades(b)
    tv = t.ibs_trades(t.session_frame(path))
    start = max(app.index.min(), tv.index.min(), pd.Timestamp("2013-06-01")); end = min(app.index.max(), tv.index.max())
    app = app[(app.index >= start) & (app.index <= end)]; tv = tv[(tv.index >= start) & (tv.index <= end)]
    yrs = (end - start).days / 365.25
    pd.set_option("display.width", 200)
    print(f"{start.date()} -> {end.date()} ({yrs:.1f} years), 1 MNQ each, after costs\n")
    print(pd.DataFrame({"App rule": stats(app.pnl, yrs), "TradingView rule": stats(tv.pnl, yrs)}).to_string())
    print(f"\nApp: average hold {app.days.mean():.2f} days; {(app.days > 1).mean():.0%} of trades held more than one day")

    cal = pd.bdate_range(start, end)
    P = pd.DataFrame({"app": app.pnl.groupby(level=0).sum().reindex(cal).fillna(0),
                      "tv": tv.pnl.groupby(level=0).sum().reindex(cal).fillna(0)})
    on_app, on_tv = P.app != 0, P.tv != 0
    print(f"\nExit days: app {on_app.sum()}, TradingView {on_tv.sum()}, both {(on_app & on_tv).sum()} "
          f"({(on_app & on_tv).sum() / on_tv.sum():.0%} of TradingView trades also an app trade)")
    for lab, m in {"all": slice(None), "2013-19": P.index.year < 2020, "2020-26": P.index.year >= 2020}.items():
        x = P[m]
        print(f"correlation {lab:8s} daily {x.app.corr(x.tv):+.2f}  monthly {x.resample('ME').sum().corr().iloc[0, 1]:+.2f}")
    P["both"] = P.app + P.tv
    eq = P.both.cumsum()
    print(f"\nBoth together: net ${P.both.sum():,.0f}, max DD ${(eq.cummax() - eq).max():,.0f}")
    yr = P.groupby(P.index.year)[["app", "tv"]].sum().round(0)
    print("\nBy year:\n" + yr.to_string())


if __name__ == "__main__":
    main()
