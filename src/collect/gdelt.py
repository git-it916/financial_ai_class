"""GDELT DOC 2.0 article lists (English headlines + seen time), monthly windows from 2017.

Each call returns at most 250 articles for its window; only title/url/seendate/domain are kept.
Rate limit: be slow (one call per ~6 s).

python -m src.collect.gdelt [--start 2017-01]
"""
from __future__ import annotations

import argparse
import json
from datetime import date

import pandas as pd

from .common import interim_path, log_manifest, polite_sleep, session, sha256_bytes, write_parquet_atomic

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERIES = {
    "krw": '("Korean won" OR "South Korean won" OR "won weakened" OR "won strengthened")',
    "korea_fx_policy": '("Bank of Korea" OR "Korea foreign exchange") (currency OR won OR market)',
    "fomc": '(FOMC OR "Federal Reserve" OR Powell) ("rate decision" OR "rate cut" OR "rate hike" OR "holds rates")',
    "us_macro": '("nonfarm payrolls" OR "consumer price index" OR "jobs report" OR "CPI report")',
}


def month_iter(y: int, m: int):
    today = date.today()
    while (y, m) <= (today.year, today.month):
        ny, nm = (y + (m == 12), m % 12 + 1)
        yield f"{y}{m:02d}01000000", f"{ny}{nm:02d}01000000", f"{y}-{m:02d}"
        y, m = ny, nm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2017-01")
    a = ap.parse_args()
    y, m = map(int, a.start.split("-"))
    s = session(retries=0)
    out = interim_path("gdelt_articles.parquet")
    old = pd.read_parquet(out) if out.exists() else None
    done = set(zip(old["query"], old["window"])) if old is not None else set()
    rows = []
    for st, en, tag in month_iter(y, m):
        for qname, q in QUERIES.items():
            if (qname, tag) in done:
                continue
            params = {"query": f"{q} sourcelang:english", "mode": "artlist", "format": "json",
                      "maxrecords": 250, "sort": "datedesc", "startdatetime": st, "enddatetime": en}
            arts, r = [], None
            for attempt in range(4):
                try:
                    r = s.get(URL, params=params, timeout=90)
                except Exception as e:
                    print(tag, qname, "error", type(e).__name__, flush=True)
                    r = None
                if r is not None and r.status_code != 429:
                    break
                polite_sleep(60 * (attempt + 1))  # GDELT asks for <= 1 call / 5 s; back off hard on 429
            if r is not None and r.ok and r.content.strip().startswith(b"{"):
                arts = json.loads(r.content).get("articles", [])
            for x in arts:
                rows.append({"query": qname, "window": tag, "title": x.get("title"), "url": x.get("url"),
                             "seendate": x.get("seendate"), "domain": x.get("domain"), "language": x.get("language")})
            print(tag, qname, len(arts), flush=True)
            polite_sleep(10)
        if rows:  # checkpoint every month so a restart loses little
            _write(old, rows, out)
    _write(old, rows, out)
    log_manifest("gdelt", URL, out, sha256_bytes(out.read_bytes()), None, "merged accumulation")


def _write(old, rows, out) -> None:
    df = pd.DataFrame(rows)
    if old is not None:
        df = pd.concat([old, df], ignore_index=True)
    if len(df):
        df["seendate_utc"] = pd.to_datetime(df["seendate"], format="%Y%m%dT%H%M%SZ", utc=True, errors="coerce")
        write_parquet_atomic(df.drop_duplicates(["query", "url"]), out)


if __name__ == "__main__":
    main()
