"""Download 1-minute Nasdaq-100 (USATECHIDXUSD) candles from Dukascopy's public datafeed.

Usage: python fetch_data.py START(YYYY-MM-DD) END(YYYY-MM-DD) OUT.parquet
"""
import lzma
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

import os

INSTR = os.environ.get("DUKA_INSTR", "USATECHIDXUSD")
URL = "http://datafeed.dukascopy.com/datafeed/{i}/{y:04d}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
SCALE = float(os.environ.get("DUKA_SCALE", "1000"))  # indices: 1000; BTCUSD: 10 (checked by inspection)
REC = struct.Struct(">IIIIIf")  # secs, open, close, low, high, volume

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (data-fetch)"


def fetch_day(day: date):
    url = URL.format(i=INSTR, y=day.year, m=day.month - 1, d=day.day)
    for attempt in range(8):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 503:
                err = "503 server busy"
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            if not r.content:
                return None
            raw = lzma.decompress(r.content)
            n = len(raw) // REC.size
            arr = np.frombuffer(raw[: n * REC.size], dtype=">u4").reshape(n, 6)
            secs = arr[:, 0].astype(np.int64)
            o, c, lo, hi = (arr[:, k].astype(np.float64) / SCALE for k in (1, 2, 3, 4))
            ts = pd.Timestamp(day, tz="UTC") + pd.to_timedelta(secs, unit="s")
            vol = np.frombuffer(raw[: n * REC.size], dtype=">f4").reshape(n, 6)[:, 5].astype(np.float64)
            df = pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": vol}, index=ts)
            # Dukascopy fills closed periods with flat candles; drop zero-range repeats
            return df
        except Exception as e:  # noqa: BLE001
            time.sleep(1 + attempt * 2)
            err = e
    print(f"FAILED {day}: {err}", file=sys.stderr)
    return None


def main():
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    out = sys.argv[3]
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() != 5]  # no Saturday sessions
    frames = []
    with ThreadPoolExecutor(max_workers=int(sys.argv[4]) if len(sys.argv) > 4 else 12) as ex:
        for i, df in enumerate(ex.map(fetch_day, days)):
            if df is not None and len(df):
                frames.append(df)
            if i % 200 == 0:
                print(f"{i}/{len(days)}", flush=True)
    data = pd.concat(frames).sort_index()
    data = data[~data.index.duplicated()]
    data.to_parquet(out)
    print(f"saved {len(data):,} rows {data.index[0]} -> {data.index[-1]}")


if __name__ == "__main__":
    main()
