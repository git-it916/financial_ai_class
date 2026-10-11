"""BIS SDMX: daily FX (period average) and central bank policy rates.

python -m src.collect.bis
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
    for name, spec in cfg["bis"]["series"].items():
        url = cfg["bis"]["url"].format(flow=spec["flow"], key=spec["key"], start=start)
        r = s.get(url, timeout=120)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content))
        save_raw("bis", f"{name}.csv", r.content, url, rows=len(df))
        df.to_parquet(interim_path(f"bis_{name}.parquet"), index=False)
        print(name, df.shape, df["TIME_PERIOD"].min(), df["TIME_PERIOD"].max())
        polite_sleep(1)


if __name__ == "__main__":
    main()
