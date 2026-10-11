"""KRX Open API: futures daily trading info -> USD futures (미국달러선물) rows, all contract months.

Needs KRX_API_KEY in .env and the '선물 일별매매정보' service approved for that key.
Full daily responses are gzipped under EXTERNAL_DATA_DIR/raw/krx; USD rows go to
data/interim/krx_usd_futures.parquet. Check whether the response separates the night
session (field names vary; all fields are kept as strings).

python -m src.collect.krx [--start 2016-01-04] [--end YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .common import env, interim_path, log_manifest, polite_sleep, session, sha256_bytes, write_parquet_atomic

URL = "https://data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd?basDd={d}"
EXTERNAL = Path(os.getenv("EXTERNAL_DATA_DIR", Path.home() / "fxbasis_data"))


def is_usd(rec: dict) -> bool:
    text = " ".join(str(v) for v in rec.values())
    return "미국달러" in text or "USD" in text.upper()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-04")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    a = ap.parse_args()
    key = env("KRX_API_KEY")
    s = session()
    s.headers["AUTH_KEY"] = key
    out = interim_path("krx_usd_futures.parquet")
    old = pd.read_parquet(out) if out.exists() else None
    done = set(old["BAS_DD"]) if old is not None and "BAS_DD" in old else set()
    recs = []
    d, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    while d <= end:
        tag = d.strftime("%Y%m%d")
        if d.weekday() < 5 and tag not in done:
            url = URL.format(d=tag)
            r = s.get(url, timeout=60)
            if r.status_code == 401:
                raise SystemExit(f"401 from KRX: {r.text[:200]} (key or service approval)")
            r.raise_for_status()
            rows = json.loads(r.content).get("OutBlock_1", [])
            if rows:
                raw = EXTERNAL / "raw" / "krx" / str(d.year) / f"fut_bydd_trd_{tag}.json.gz"
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(gzip.compress(r.content))
                usd = [x for x in rows if is_usd(x)]
                recs.extend(usd)
                log_manifest("krx", url, raw, sha256_bytes(r.content), len(rows), f"usd rows {len(usd)}")
                print(tag, len(rows), "rows,", len(usd), "USD", flush=True)
            polite_sleep(0.2)
        d += timedelta(days=1)
        if d.day == 1 and recs:  # monthly checkpoint so a crash/limit midway keeps progress
            _save(old, recs, out)
    _save(old, recs, out)


def _save(old: pd.DataFrame | None, recs: list[dict], out: Path) -> None:
    new = pd.DataFrame(recs)
    if old is not None:
        new = pd.concat([old, new], ignore_index=True)
    if len(new):
        write_parquet_atomic(new.astype("string").drop_duplicates(), out)
        print("saved", len(new), "rows; columns:", list(new.columns), flush=True)


if __name__ == "__main__":
    main()
