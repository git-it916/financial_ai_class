"""Naver news search API: accumulate recent headlines (no date filter; max 1,100 per query).

Run daily. Needs NAVER_CLIENT_ID / NAVER_CLIENT_SECRET.
Only title/description/link/pubDate are stored (no article bodies).

python -m src.collect.naver
"""
from __future__ import annotations

import pandas as pd

from .common import env, interim_path, log_manifest, polite_sleep, session, sha256_bytes, write_parquet_atomic

URL = "https://openapi.naver.com/v1/search/news.json"
QUERIES = [
    "NDF 최종호가", "역외 NDF 원달러", "원달러 환율 마감", "원달러 야간", "외환시장 24시간",
    "스왑포인트 원달러", "FOMC 환율", "미국 CPI 환율", "외환당국 개입",
]


def main() -> None:
    s = session()
    s.headers["X-Naver-Client-Id"] = env("NAVER_CLIENT_ID")
    s.headers["X-Naver-Client-Secret"] = env("NAVER_CLIENT_SECRET")
    items = []
    for q in QUERIES:
        for start in range(1, 1001, 100):
            r = s.get(URL, params={"query": q, "display": 100, "start": start, "sort": "date"}, timeout=30)
            r.raise_for_status()
            got = r.json().get("items", [])
            for it in got:
                it["query"] = q
            items.extend(got)
            if len(got) < 100:
                break
            polite_sleep(0.2)
        print(q, "done", flush=True)
    df = pd.DataFrame(items)
    df["pubDate"] = pd.to_datetime(df["pubDate"], format="%a, %d %b %Y %H:%M:%S %z", utc=True)
    out = interim_path("naver_news.parquet")
    if out.exists():
        df = pd.concat([pd.read_parquet(out), df], ignore_index=True)
    df = df.drop_duplicates(["query", "link"]).sort_values("pubDate")
    write_parquet_atomic(df, out)
    log_manifest("naver", URL, out, sha256_bytes(out.read_bytes()), len(df), "merged accumulation")
    print(len(df), "rows", df["pubDate"].min(), "~", df["pubDate"].max())


if __name__ == "__main__":
    main()
