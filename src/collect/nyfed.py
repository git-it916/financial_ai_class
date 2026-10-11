"""NY Fed reference rates (SOFR with percentiles/volume, EFFR), yearly chunks.

python -m src.collect.nyfed
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import yaml

from .common import ROOT, interim_path, polite_sleep, save_raw, session


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    s = session()
    rows = []
    for name, tmpl in [("sofr", cfg["nyfed"]["sofr_search"]), ("effr", cfg["nyfed"]["effr_search"])]:
        first = 2018 if name == "sofr" else 2016
        for y in range(first, date.today().year + 1):
            url = tmpl.format(start=f"{y}-01-01", end=f"{y}-12-31")
            r = s.get(url, timeout=60)
            r.raise_for_status()
            recs = json.loads(r.content).get("refRates", [])
            save_raw("nyfed", f"{name}_{y}.json", r.content, url, year=None, rows=len(recs))
            rows.extend(recs)
            polite_sleep(0.5)
        print(f"{name}: done")
    df = pd.DataFrame(rows)
    df["effectiveDate"] = pd.to_datetime(df["effectiveDate"])
    for c in df.columns:
        if c.startswith(("percent", "volume", "target")):
            df[c] = pd.to_numeric(df[c], errors="coerce")  # "NA" in early rows
    df = df.astype({c: "string" for c in df.columns if df[c].dtype == object})
    df = df.sort_values(["type", "effectiveDate"]).drop_duplicates(["type", "effectiveDate"], keep="last")
    df.to_parquet(interim_path("nyfed_rates.parquet"), index=False)
    print(df.groupby("type")["effectiveDate"].agg(["min", "max", "count"]))


if __name__ == "__main__":
    main()
