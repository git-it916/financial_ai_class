"""FRED daily series via the keyless fredgraph CSV endpoint.

python -m src.collect.fred
"""
from __future__ import annotations

import io

import pandas as pd
import yaml

from .common import ROOT, interim_path, polite_sleep, save_raw, session


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    start = str(cfg["start_date"])
    s = session()
    frames = []
    for sid in cfg["fred"]["series"]:
        url = cfg["fred"]["csv_url"].format(id=sid, start=start)
        r = s.get(url, timeout=60)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
        save_raw("fred", f"{sid}.csv", r.content, url, rows=len(df))
        df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")  # "." = missing
        df["series"] = sid
        frames.append(df)
        print(f"{sid}: {len(df)} rows, {df['date'].min()} ~ {df['date'].max()}")
        polite_sleep(0.5)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out.to_parquet(interim_path("fred_daily.parquet"), index=False)


if __name__ == "__main__":
    main()
