"""Bankers Association of the Philippines: USD/PHP daily OHLC, weighted averages, volume.

Monthly HTML tables exist from mid-2021; earlier months are PDF-only (not handled here).

python -m src.collect.bap [--start 2021-01]
"""
from __future__ import annotations

import argparse
from datetime import date

import pandas as pd
from bs4 import BeautifulSoup

from .common import BROWSER_UA, interim_path, polite_sleep, save_raw, session

URL = "https://bap.org.ph/fxhistorical.html?base=USD&quote=PHP&year={y}&month={m}"


def parse(html: str) -> pd.DataFrame:
    t = BeautifulSoup(html, "lxml").find("table")
    if t is None:
        return pd.DataFrame()
    head = [h for h in (th.get_text(strip=True) for th in t.find_all("th")) if h]
    rows = []
    for tr in t.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if cells and cells[0][:2] == "20" and len(cells) > 3:
            rows.append(cells)
    if not rows:
        return pd.DataFrame()
    cols = ["date"] + head if head and head[0] != "Date" else head
    return pd.DataFrame(rows, columns=cols[: len(rows[0])])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01")
    a = ap.parse_args()
    y, m = map(int, a.start.split("-"))
    s = session(ua=BROWSER_UA)
    frames = []
    today = date.today()
    while (y, m) <= (today.year, today.month):
        url = URL.format(y=y, m=m)
        r = s.get(url, timeout=60)
        r.raise_for_status()
        df = parse(r.text)
        if len(df):
            save_raw("bap", f"usdphp_{y}{m:02d}.html", r.content, url, year=y, rows=len(df))
            frames.append(df)
            print(f"{y}-{m:02d}: {len(df)}", flush=True)
        y, m = (y + (m == 12), m % 12 + 1)
        polite_sleep(1)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    for c in out.columns[2:]:
        out[c] = pd.to_numeric(out[c].str.replace(",", ""), errors="coerce")
    out.sort_values("date").to_parquet(interim_path("bap_usdphp.parquet"), index=False)
    print(out.shape, out["date"].min().date(), out["date"].max().date())


if __name__ == "__main__":
    main()
