"""Central Bank of the Republic of China (Taiwan) open data.

- FTDOpenData_Day: TWD/USD interbank closing rate (Taipei Forex), daily
- EG37D01: interbank call rates by tenor, daily
- EG55M01 / EG55D01: one bank's customer forward rates 10~180 days (buy/sell)

python -m src.collect.cbc_tw
"""
from __future__ import annotations

import itertools
import json

import pandas as pd
import yaml

from .common import ROOT, interim_path, polite_sleep, save_raw, session


def parse_px(payload: dict) -> pd.DataFrame:
    """dataSets rows are [period, v1, v2, ...]; columns are the product of structure tables."""
    tables = [[c["data"] for c in t] for t in payload["data"]["structure"].values()]
    cols = ["-".join(p) for p in itertools.product(*tables)]
    rows = payload["data"]["dataSets"]
    df = pd.DataFrame(rows)
    if df.shape[1] - 1 != len(cols):  # fall back to the first table only
        cols = tables[0]
    df.columns = ["period"] + cols[: df.shape[1] - 1]
    long = df.melt(id_vars="period", var_name="item", value_name="value")
    long["value"] = pd.to_numeric(long["value"].replace("-", None), errors="coerce")
    return long


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))["cbc_tw"]
    s = session(non_strict_x509=True)

    url = cfg["closing_daily"]
    r = s.get(url, timeout=120)
    r.raise_for_status()
    recs = json.loads(r.content.decode("utf-8-sig"))
    save_raw("cbc_tw", "FTDOpenData_Day.json", r.content, url, rows=len(recs))
    df = pd.DataFrame(recs).rename(columns={"日期": "date", "NTD_USD": "twd_per_usd"})
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["twd_per_usd"] = pd.to_numeric(df["twd_per_usd"], errors="coerce")
    df.to_parquet(interim_path("cbc_tw_closing.parquet"), index=False)
    print("closing", df.shape, df["date"].min().date(), df["date"].max().date())

    for name, code in cfg["codes"].items():
        url = cfg["stats"].format(code=code)
        for attempt in range(3):  # EG55D01 occasionally returns a server error
            r = s.get(url, timeout=180)
            if r.ok:
                break
            polite_sleep(5)
        r.raise_for_status()
        payload = json.loads(r.content.decode("utf-8-sig"))
        long = parse_px(payload)
        save_raw("cbc_tw", f"{code}.json", r.content, url, rows=len(long))
        long.to_parquet(interim_path(f"cbc_tw_{name}.parquet"), index=False)
        print(name, code, long.shape, long["period"].min(), long["period"].max(), long["item"].nunique(), "items")
        polite_sleep(1)


if __name__ == "__main__":
    main()
