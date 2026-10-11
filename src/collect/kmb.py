"""Korea Money Brokerage (KMB): USD/KRW daily (MAR, OHLC, volume) and FX swap points by tenor.

Swap points: one POST per date returns 1M/2M/3M/6M/1Y BID/OFFER in jeon (/100 = KRW).
The range export only has 1Y, so we loop dates (slow server: ~5-20 s per request).
Both histories are shallow (roughly 2023 onward); empty/all-zero dates are skipped.

python -m src.collect.kmb [fx|swap] [--start 2023-01-01]
"""
from __future__ import annotations

import argparse
import io
from datetime import date, timedelta

import pandas as pd
from bs4 import BeautifulSoup

from .common import BROWSER_UA, interim_path, polite_sleep, save_raw, session, write_parquet_atomic

FX_XLS = "https://www.kmbco.com/kor/rate/exchange_rate_excel.do?dType=USD&sDate={s}&eDate={e}"
SWAP = "https://www.kmbco.com/kor/rate/swap_rate.do"
FX_COLS = ["date", "mar", "chg", "open", "high", "low", "close", "volume_musd"]


def collect_fx(start: date) -> None:
    s = session(ua=BROWSER_UA)
    frames = []
    m = date(start.year, start.month, 1)
    while m <= date.today():
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        url = FX_XLS.format(s=m.isoformat(), e=(nxt - timedelta(days=1)).isoformat())
        r = s.get(url, timeout=120)
        r.raise_for_status()
        df = pd.read_excel(io.BytesIO(r.content), header=None, skiprows=1)
        if len(df):
            save_raw("kmb", f"fx_{m:%Y%m}.xls", r.content, url, year=m.year, rows=len(df))
            df.columns = FX_COLS[: df.shape[1]]
            frames.append(df)
            print(f"fx {m:%Y-%m}: {len(df)}", flush=True)
        m = nxt
        polite_sleep(1)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], format="%Y/%m/%d")
    for c in FX_COLS[1:]:
        out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", ""), errors="coerce")
    out.sort_values("date").to_parquet(interim_path("kmb_fx.parquet"), index=False)
    print("fx", out["date"].min().date(), out["date"].max().date(), len(out))


def parse_swap(html: str) -> dict | None:
    t = BeautifulSoup(html, "lxml").find("table", class_="list")
    rows = [[td.get_text(strip=True) for td in tr.find_all("td")] for tr in t.find("tbody").find_all("tr")]
    tenors = ["1M", "2M", "3M", "6M", "1Y"]
    rec = {}
    for row in rows:
        side = row[0].lower()
        for k, v in zip(tenors, row[1:]):
            rec[f"{side}_{k}"] = pd.to_numeric(v.replace(",", ""), errors="coerce")
    if not rec or all((v == 0 or pd.isna(v)) for v in rec.values()):
        return None
    return rec


def collect_swap(start: date) -> None:
    out_path = interim_path("kmb_swap.parquet")
    done = set()
    old = None
    if out_path.exists():
        old = pd.read_parquet(out_path)
        done = set(old["date"].dt.date)
    s = session(ua=BROWSER_UA)
    recs, d = [], start
    while d < date.today():
        if d.weekday() < 5 and d not in done:
            r = None
            for attempt in range(5):  # the server resets connections now and then
                try:
                    r = s.post(SWAP, data={"s_date_sh": d.isoformat()}, timeout=120)
                    r.raise_for_status()
                    break
                except Exception as e:
                    print(d, "retry", attempt + 1, type(e).__name__, flush=True)
                    polite_sleep(10 * (attempt + 1))
                    s = session(ua=BROWSER_UA)
            if r is None or not r.ok:
                print(d, "giving up", flush=True)
                d += timedelta(days=1)
                continue
            rec = parse_swap(r.content.decode("utf-8", "replace"))
            if rec:
                save_raw("kmb", f"swap_{d:%Y%m%d}.html", r.content, f"{SWAP} s_date_sh={d}", year=d.year, rows=1)
                recs.append({"date": pd.Timestamp(d), **rec})
                print(d, rec["bid_1M"], rec["offer_1M"], flush=True)
            if len(recs) and len(recs) % 20 == 0:  # checkpoint
                _write_swap(old, recs, out_path)
            polite_sleep(1)
        d += timedelta(days=1)
    _write_swap(old, recs, out_path)


def _write_swap(old, recs, path) -> None:
    new = pd.DataFrame(recs)
    if old is not None:
        new = pd.concat([old, new], ignore_index=True)
    if len(new):
        write_parquet_atomic(new.drop_duplicates("date", keep="last").sort_values("date"), path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["fx", "swap"])
    ap.add_argument("--start", default=None)
    a = ap.parse_args()
    if a.what == "fx":
        collect_fx(date.fromisoformat(a.start or "2016-01-01"))
    else:
        collect_swap(date.fromisoformat(a.start or "2023-01-02"))


if __name__ == "__main__":
    main()
