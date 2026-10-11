"""FOMC meeting dates (2016~) from federalreserve.gov -> statement date and KST time.

Statement time is assumed 14:00 ET (scheduled meetings); unscheduled ones are flagged
and need their actual release time checked by hand (2020-03-03 10:00 ET, 2020-03-15 ~17:00 ET).

python -m src.collect.fomc
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

from .common import interim_path, polite_sleep, save_raw, session

CUR = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
HIST = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
ABBR = {k[:3]: v for k, v in MONTHS.items()}


def last_day(year: int, month_txt: str, days_txt: str) -> date:
    """'March','17-18*' -> 2026-03-18; 'Jul/Aug','31-1' -> 08-01."""
    mt = month_txt.lower().replace(".", "")
    days = [int(x) for x in re.findall(r"\d+", days_txt)]
    if "/" in mt:
        m = ABBR[mt.split("/")[1].strip()[:3]]
    else:
        m = MONTHS.get(mt, ABBR.get(mt[:3]))
    return date(year, m, days[-1])


def kst(d: date, hhmm: str = "14:00") -> str:
    h, mi = map(int, hhmm.split(":"))
    et = datetime(d.year, d.month, d.day, h, mi, tzinfo=ZoneInfo("America/New_York"))
    return et.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    s = session()
    rows = []
    r = s.get(CUR, timeout=60)
    r.raise_for_status()
    save_raw("fomc", "fomccalendars.htm", r.content, CUR)
    b = BeautifulSoup(r.text, "lxml")
    for p in b.select("div.panel.panel-default"):
        h = p.select_one(".panel-heading")
        m = re.search(r"(\d{4}) FOMC Meetings", h.get_text(" ", strip=True)) if h else None
        if not m:
            continue
        y = int(m.group(1))
        for mt in p.select(".fomc-meeting"):
            month = mt.select_one(".fomc-meeting__month").get_text(strip=True)
            days = mt.select_one(".fomc-meeting__date").get_text(" ", strip=True)
            unsched = "unscheduled" in mt.get_text(" ", strip=True).lower()
            if "notation" in days.lower():
                continue
            rows.append({"year": y, "month_txt": month, "days_txt": days, "unscheduled": unsched,
                         "sep": "*" in days, "source": "current"})

    for y in range(2016, 2021):
        url = HIST.format(y=y)
        r = s.get(url, timeout=60)
        r.raise_for_status()
        save_raw("fomc", f"fomchistorical{y}.htm", r.content, url)
        for h in BeautifulSoup(r.text, "lxml").select("h5, .panel-heading"):
            t = h.get_text(" ", strip=True)
            # e.g. "March 2 (unscheduled) Meeting - 2020"; skip notation votes and cancelled meetings
            m = re.match(r"([A-Za-z/]+)\s+([\d\-]+)\s*(\([^)]*\))?\s*Meeting\s*-\s*(\d{4})", t)
            if m and "cancelled" not in t.lower():
                rows.append({"year": int(m.group(4)), "month_txt": m.group(1), "days_txt": m.group(2),
                             "unscheduled": "unscheduled" in (m.group(3) or "").lower(), "sep": None,
                             "source": "historical"})
        polite_sleep(1)

    df = pd.DataFrame(rows)
    df["statement_date"] = [last_day(a, b_, c) for a, b_, c in zip(df.year, df.month_txt, df.days_txt)]
    df = df[df["year"] >= 2016].drop_duplicates("statement_date").sort_values("statement_date")
    df["statement_et"] = df["statement_date"].astype(str) + " 14:00"
    df["statement_kst"] = df["statement_date"].map(kst)
    df["statement_date"] = pd.to_datetime(df["statement_date"])
    df.to_parquet(interim_path("fomc_meetings.parquet"), index=False)
    print(df[["statement_date", "statement_kst", "unscheduled"]].tail(12).to_string(index=False))
    print(len(df), "meetings;", df["unscheduled"].sum(), "unscheduled")


if __name__ == "__main__":
    main()
