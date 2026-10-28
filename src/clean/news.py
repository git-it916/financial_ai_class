"""Naver news -> data/processed/news_ndf.parquet: NY 'NDF 1개월물 최종 호가' and the Seoul broker 1M swap point.

Two sentence forms: '1173.1/1173.6원에 최종 호가' (bid/ask) and '1,440.50원에 최종 호가'.
The article says 'N일(현지시간)'; ny_date is the latest date on or before publication with day N.
Without it ('간밤…', '[환율마감]…'), the quote is the NY session that closed the morning of publication,
so ny_date = previous weekday before the KST publication date (date_inferred=True).
python -m src.clean.news
"""
from __future__ import annotations

import re

import pandas as pd

from ..collect.common import INTERIM, ROOT
from . import cleanlog

OUT = ROOT / "data" / "processed" / "news_ndf.parquet"
NUM = r"(\d{1,2},?\d{3}\.\d{1,2})"
PRICE = re.compile(rf"1개월물은?\s*{NUM}(?:\s*/\s*{NUM})?\s*원에\s*최종\s*호가")
SWAP = re.compile(r"1개월물\s*스(?:왑|와프)\s*포인트\s*\(?([+\-−]?\s*\d+\.\d+)\s*원")
DAY = re.compile(r"(\d{1,2})일\s*\(현지\s*시간\)")


def _f(s: str | None) -> float | None:
    return None if s is None else float(s.replace(",", "").replace("−", "-").replace(" ", ""))


def ny_date(pub: pd.Timestamp, day: int) -> pd.Timestamp | None:
    d = pub.normalize().tz_localize(None)
    for back in range(0, 7):
        c = d - pd.Timedelta(days=back)
        if c.day == day:
            # Monday articles write Saturday's date for the Friday NY session (closes Sat 06:00 KST)
            return c - pd.offsets.BDay(0) if c.weekday() < 5 else c - pd.Timedelta(days=c.weekday() - 4)
    return None


def parse(row: pd.Series) -> dict | None:
    text = re.sub(r"<[^>]+>", "", f"{row['title']} {row['description']}")
    p = PRICE.search(text)
    if not p:
        return None
    m = DAY.search(text)
    pub = pd.to_datetime(row["pubDate"], format="%a, %d %b %Y %H:%M:%S %z").tz_convert("Asia/Seoul")
    bid, ask = _f(p.group(1)), _f(p.group(2))
    s = SWAP.search(text)
    prev_weekday = (pub.normalize().tz_localize(None) - pd.offsets.BDay(1))
    return {
        "ny_date": ny_date(pub, int(m.group(1))) if m else prev_weekday,
        "date_inferred": m is None,
        "pub_kst": pub, "ndf_1m": (bid + ask) / 2 if ask else bid, "ndf_bid": bid, "ndf_ask": ask,
        "swap_1m_smb": _f(s.group(1)) if s else None, "link": row["originallink"] or row["link"], "text": text[:300],
    }


def main() -> None:
    cleanlog.reset("news")
    n = pd.read_parquet(INTERIM / "naver_news.parquet").drop_duplicates("link")
    parsed = [r for r in (parse(x) for _, x in n.iterrows()) if r]
    p = pd.DataFrame(parsed)
    cleanlog.record("news", "01_parse", "drop", len(n), len(p),
                    "kept articles containing an 'NDF 1개월물 ... 최종 호가' price sentence", affected=len(n) - len(p))
    cleanlog.record("news", "02_date_inferred", "flag", len(p), len(p),
                    "no 'N일(현지시간)': ny_date = previous weekday of KST publication date", rows=p[p.date_inferred],
                    affected=int(p.date_inferred.sum()))
    nodate = p.ny_date.isna()
    cleanlog.record("news", "02_no_date", "drop", len(p), len(p) - int(nodate.sum()),
                    "'N일(현지시간)' did not match any of the 7 days before publication", rows=p[nodate])
    p = p[~nodate]
    # one value per NY date: several outlets repeat the same wire; disagreeing values are logged
    g = p.groupby("ny_date").ndf_1m
    spread = (g.transform("max") - g.transform("min"))
    cleanlog.record("news", "03_conflicts", "flag", len(p), len(p),
                    "same NY date reported with different prices across articles (>0.5 won)",
                    rows=p[spread > 0.5], affected=int((spread > 0.5).sum()))
    out = p.sort_values("pub_kst").groupby("ny_date").agg(
        ndf_1m=("ndf_1m", "median"), ndf_bid=("ndf_bid", "median"), ndf_ask=("ndf_ask", "median"),
        swap_1m_smb=("swap_1m_smb", "median"), n_articles=("link", "size"), first_pub_kst=("pub_kst", "min"), date_inferred=("date_inferred", "all")).reset_index()
    cleanlog.record("news", "04_collapse", "drop", len(p), len(out), "collapsed to one row per NY date (median)",
                    affected=len(p) - len(out))
    out.to_parquet(OUT, index=False)
    cleanlog.record("news", "99_saved", "info", len(out), len(out),
                    f"saved {OUT.relative_to(ROOT)}; {out.ny_date.min().date()} ~ {out.ny_date.max().date()}", affected=0)


if __name__ == "__main__":
    main()
