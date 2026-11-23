"""Download 1-minute NQ futures bars (CME Globex, front month by volume) from Databento.

Needs a Databento API key in the DATABENTO_API_KEY environment variable (never put it in this file).

Usage:
  python fetch_futures.py --cost                 # show the price of the download, download nothing
  python fetch_futures.py OUT.parquet            # download 2010-06-06 .. END and save

Options: --symbol NQ.v.0  --start 2010-06-06  --end 2026-11-21
  NQ.v.0 = continuous front contract, rolled to the highest-volume contract each day.
  Prices are not back-adjusted, so a roll shows as a jump between days; the ORB only uses
  prices within one London day (07:30-20:55) and its range ATR (00:00-21:00), so rolls do not leak in.
"""
import argparse
import os
import sys

import pandas as pd

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--cost", action="store_true")
    ap.add_argument("--symbol", default="NQ.v.0")
    ap.add_argument("--start", default="2010-06-06")
    ap.add_argument("--end", default="2026-11-21")
    a = ap.parse_args()

    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        sys.exit("Set DATABENTO_API_KEY first (see README).")
    import databento as db

    client = db.Historical(key)
    q = dict(dataset=DATASET, symbols=[a.symbol], stype_in="continuous", schema=SCHEMA)
    cost = client.metadata.get_cost(start=a.start, end=a.end, **q)
    print(f"{a.symbol} {SCHEMA} {a.start} -> {a.end}: estimated cost ${cost:,.2f}")
    if a.cost or not a.out:
        return

    frames = []
    years = range(int(a.start[:4]), int(a.end[:4]) + 1)
    for y in years:
        s = max(a.start, f"{y}-01-01"); e = min(a.end, f"{y + 1}-01-01")
        df = client.timeseries.get_range(start=s, end=e, **q).to_df()
        df = df[["open", "high", "low", "close", "volume"]].astype("float64")
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
        print(f"{y}: {len(df):,} bars", flush=True)
        frames.append(df)
    data = pd.concat(frames).sort_index()
    data = data[~data.index.duplicated()]
    data.to_parquet(a.out)
    print(f"saved {len(data):,} rows {data.index[0]} -> {data.index[-1]} to {a.out}")


if __name__ == "__main__":
    main()
