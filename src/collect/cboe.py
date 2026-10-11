"""CBOE VIX daily OHLC history (cross-check for FRED VIXCLS).

python -m src.collect.cboe
"""
from __future__ import annotations

import io

import pandas as pd
import yaml

from .common import ROOT, interim_path, save_raw, session


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    url = cfg["cboe"]["vix_csv"]
    r = session().get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content))
    save_raw("cboe", "VIX_History.csv", r.content, url, rows=len(df))
    df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
    df.to_parquet(interim_path("cboe_vix.parquet"), index=False)
    print(df.shape, df["DATE"].min(), df["DATE"].max())


if __name__ == "__main__":
    main()
