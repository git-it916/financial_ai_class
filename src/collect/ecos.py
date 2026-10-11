"""Bank of Korea ECOS: USD/KRW (open/high/low/15:30 close/close), MAR, control currencies, short rates.

Needs ECOS_API_KEY in .env.

python -m src.collect.ecos
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import yaml

from .common import ROOT, env, interim_path, polite_sleep, save_raw, session

PAGE = 10000


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    key = env(cfg["ecos"]["key_env"])
    frm = pd.Timestamp(cfg["start_date"]).strftime("%Y%m%d")
    to = date.today().strftime("%Y%m%d")
    s = session()
    frames = []
    for name, spec in cfg["ecos"]["series"].items():
        rows, start = [], 1
        while True:
            url = cfg["ecos"]["url"].format(key=key, start=start, end=start + PAGE - 1, stat=spec["stat"],
                                            cycle="D", **{"from": frm}, to=to, item=spec["item"])
            r = s.get(url, timeout=120)
            r.raise_for_status()
            j = json.loads(r.content)
            if "StatisticSearch" not in j:  # e.g. {"RESULT": {"CODE": "INFO-200", ...}} = no data
                print(name, j.get("RESULT"))
                break
            block = j["StatisticSearch"]
            rows.extend(block["row"])
            save_raw("ecos", f"{name}_{start}.json", r.content, url.replace(key, "{KEY}"), rows=len(block["row"]))
            if start + PAGE - 1 >= int(block["list_total_count"]):
                break
            start += PAGE
            polite_sleep(0.5)
        if rows:
            df = pd.DataFrame(rows)
            df["series"] = name
            frames.append(df)
            print(f"{name}: {len(df)} rows {df['TIME'].min()} ~ {df['TIME'].max()} | {df['ITEM_NAME1'].iloc[0]} [{df['UNIT_NAME'].iloc[0]}]")
        polite_sleep(0.5)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["TIME"], format="%Y%m%d")
    out["value"] = pd.to_numeric(out["DATA_VALUE"], errors="coerce")
    out.to_parquet(interim_path("ecos_daily.parquet"), index=False)


if __name__ == "__main__":
    main()
