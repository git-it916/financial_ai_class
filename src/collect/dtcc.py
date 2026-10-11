"""DTCC public price dissemination (CFTC) cumulative FOREX files -> KRW/TWD/IDR/PHP/INR rows.

The PPD site (pddata.dtcc.com) was returning 503 on 2026-10-11; the same files are
served from DTCC's public S3 bucket, which also holds older files (weekly before ~2022,
daily after). Raw zips and filtered rows live under EXTERNAL (default data/external,
gitignored but synced by OneDrive): raw/dtcc/{YYYY}/*.zip, interim/dtcc/{YYYY}/{date}.parquet.
Missing dates are logged to data/interim/dtcc_missing.csv.

python -m src.collect.dtcc [--start 2020-10-01] [--end YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import yaml

from .common import EXTERNAL, ROOT, interim_path, log_manifest, polite_sleep, session, sha256_bytes

S3 = "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/CFTC_CUMULATIVE_FOREX_{d}.zip"
PPD = "https://pddata.dtcc.com/ppd/api/report/cumulative/cftc/CFTC_CUMULATIVE_FOREX_{d}.zip"
# PPD is tried only with --ppd (it was 503 on 2026-10-11 and its retries slow down missing dates).
MIRRORS = [S3]
RAW_DIR = EXTERNAL / "raw" / "dtcc"
OUT_DIR = EXTERNAL / "interim" / "dtcc"


def filter_rows(df: pd.DataFrame, keep: set[str]) -> pd.DataFrame:
    """Keep rows where any currency-like column (or the underlier/product text) mentions a kept currency."""
    cur_cols = [c for c in df.columns if "currency" in c.lower() or "CURRENCY" in c]
    mask = pd.Series(False, index=df.index)
    for c in cur_cols:
        mask |= df[c].astype("string").str.upper().isin(keep).fillna(False)
    for c in [c for c in df.columns if any(k in c.lower() for k in ("underlier", "underlying", "upi"))]:
        pat = "|".join(sorted(keep))
        mask |= df[c].astype("string").str.upper().str.contains(pat, regex=True).fillna(False)
    return df[mask]


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def fetch_day(s, d: date, keep: set[str]) -> str:
    tag = d.strftime("%Y_%m_%d")
    out = OUT_DIR / str(d.year) / f"{d.isoformat()}.parquet"
    if out.exists():
        try:  # a run killed mid-write can leave a truncated file; refetch it
            pq.read_metadata(out)
            return "skip"
        except Exception:
            out.unlink()
    for tmpl in MIRRORS:
        url = tmpl.format(d=tag)
        try:
            r = s.get(url, timeout=120)
        except Exception:
            continue
        if r.status_code != 200 or not r.content.startswith(b"PK"):
            continue
        raw = RAW_DIR / str(d.year) / f"CFTC_CUMULATIVE_FOREX_{tag}.zip"
        raw.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(raw, r.content)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        frames = [pd.read_csv(z.open(n), dtype=str, low_memory=False) for n in z.namelist() if n.lower().endswith(".csv")]
        df = pd.concat(frames, ignore_index=True)
        sub = filter_rows(df, keep).copy()
        sub.insert(0, "file_date", d.isoformat())
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".parquet.tmp")
        sub.to_parquet(tmp, index=False)
        tmp.replace(out)  # write-then-rename so a crash never leaves a half file under the real name
        log_manifest("dtcc", url, raw, sha256_bytes(r.content), len(df), f"kept {len(sub)} rows -> {out.name}")
        return f"ok {len(df)}->{len(sub)}"
    return "missing"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-10-09")  # rolling ~2-year retention; oldest go first
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    ap.add_argument("--ppd", action="store_true", help="also try pddata.dtcc.com")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.ppd:
        MIRRORS.append(PPD)
    keep = set(yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))["dtcc"]["keep_currencies"])
    d0, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    days = [d0 + timedelta(days=i) for i in range((end - d0).days + 1)]

    def work(d: date) -> tuple[date, str]:
        return d, fetch_day(session(retries=2, backoff=1.0), d, keep)

    missing = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for d, status in ex.map(work, days):
            if status == "missing":
                missing.append(d.isoformat())
            elif status != "skip":
                print(d, status, flush=True)
    mpath = interim_path("dtcc_missing.csv")
    pd.DataFrame({"date": missing}).to_csv(mpath, index=False)
    print(f"missing {len(missing)} dates -> {mpath}")


if __name__ == "__main__":
    main()
