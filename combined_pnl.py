"""P&L of the three strategies in use, separately and together (see STRATEGIES.md).

  * ORB preset E, 1 MNQ (futures_test.daily_pnl)
  * IBS phone-app rule, 1 MNQ equivalent (ibs_app_vs_tv.app_trades)
  * BTC 4h SFP+VOL, $10k account: TradingView backtest trades on PHEMEX:BTCUSDT.P 4h (sfp_vol_trades.csv,
    exit date and P&L per trade, exported 24 Nov 2026)

Usage: python combined_pnl.py nq_1m_2012_2026.parquet
"""
import sys

import pandas as pd

import futures_test as f
import ibs_app_vs_tv as a


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    e, _ = f.daily_pnl(path)
    e.index = e.index.tz_localize(None) if e.index.tz else e.index
    ibs = a.app_trades(a.cash_bars(path)).pnl.groupby(level=0).sum()
    sfp = pd.read_csv("sfp_vol_trades.csv", parse_dates=["date"]).groupby("date").pnl.sum()
    cal = pd.date_range("2013-06-01", max(e.index.max(), sfp.index.max()))
    P = pd.DataFrame({"ORB E": e.reindex(cal).fillna(0), "IBS app": ibs.reindex(cal).fillna(0),
                      "SFP+VOL": sfp.reindex(cal).fillna(0)})
    P["All"] = P.sum(axis=1)

    def stats(df):
        eq = df.cumsum()
        return pd.DataFrame({"net $": df.sum().round(0), "max DD $": (eq.cummax() - eq).max().round(0)})

    pd.set_option("display.width", 200)
    print(f"{cal[0].date()} -> {cal[-1].date()}\n" + stats(P).to_string())
    print("\nSince Dec 2022 (all three running):\n" + stats(P[P.index >= "2022-12-01"]).to_string())
    print("\nBy year:\n" + P.groupby(P.index.year).sum().round(0).to_string())
    P.resample("ME").sum().cumsum().round(0).to_csv("combined_pnl_monthly.csv")


if __name__ == "__main__":
    main()
