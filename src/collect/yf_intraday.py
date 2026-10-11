"""Yahoo Finance FX bars (offshore composite quotes, auxiliary only).

History limits: 1m ~30 days (7 days per request), 5m 60 days, 1h 730 days.
Run daily to accumulate; each run merges into data/interim/yf_{interval}.parquet.

python -m src.collect.yf_intraday
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import yaml
import yfinance as yf

from .common import ROOT, interim_path, log_manifest, polite_sleep, sha256_bytes, write_parquet_atomic

PLAN = [  # interval, lookback days, chunk days
    ("1m", 29, 7),
    ("5m", 59, 59),
    ("1h", 729, 729),
    ("1d", None, None),
]


def fetch(ticker: str, interval: str, start: datetime | None, end: datetime | None) -> pd.DataFrame:
    kw = dict(interval=interval, auto_adjust=False, progress=False, threads=False)
    if start is None:
        df = yf.download(ticker, start="2016-01-01", **kw)
    else:
        df = yf.download(ticker, start=start, end=end, **kw)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={"Datetime": "ts", "Date": "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["ticker"] = ticker
    return df


def main() -> None:
    tickers = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))["yfinance"]["tickers"]
    now = datetime.now(timezone.utc)
    for interval, lookback, chunk in PLAN:
        frames = []
        for t in tickers:
            if lookback is None:
                frames.append(fetch(t, interval, None, None))
            else:
                start = now - timedelta(days=lookback)
                while start < now:
                    end = min(start + timedelta(days=chunk), now)
                    frames.append(fetch(t, interval, start, end))
                    start = end
                    polite_sleep(0.5)
        new = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        out = interim_path(f"yf_{interval}.parquet")
        if out.exists():
            new = pd.concat([pd.read_parquet(out), new], ignore_index=True)
        new = new.drop_duplicates(["ticker", "ts"], keep="last").sort_values(["ticker", "ts"])
        write_parquet_atomic(new, out)
        log_manifest("yfinance", f"yf.download interval={interval}", out,
                     sha256_bytes(out.read_bytes()), len(new), "merged accumulation")
        print(interval, new.groupby("ticker")["ts"].agg(["min", "max", "count"]).to_string())


if __name__ == "__main__":
    main()
