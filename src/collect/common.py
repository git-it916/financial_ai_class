"""Shared helpers for collectors: paths, HTTP session with retries, manifest logging."""
from __future__ import annotations

import csv
import hashlib
import os
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
# Large files (DTCC zips/daily rows, KRX raw). Inside the OneDrive project folder so another PC
# picks them up, but gitignored. Override with EXTERNAL_DATA_DIR.
MANIFEST = ROOT / "manifest.csv"
_MANIFEST_LOCK = threading.Lock()
MANIFEST_FIELDS = ["fetched_at_utc", "source", "url", "path", "sha256", "rows", "note"]

load_dotenv(ROOT / ".env", override=True)  # .env wins over stale OS env vars
EXTERNAL = Path(os.getenv("EXTERNAL_DATA_DIR") or ROOT / "data" / "external")

# Honest default UA. Some sites tarpit browser-like UAs (FRED); others need one (pass ua=BROWSER_UA).
UA = "fx-basis-research/0.1 (academic project; python-requests)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def env(name: str, required: bool = True) -> str | None:
    val = os.getenv(name)
    if required and not val:
        raise SystemExit(f"[{name}] is not set. Add it to .env (see .env.example).")
    return val


class _NonStrictX509Adapter(HTTPAdapter):
    """Certificates are still verified; only Python 3.13+'s VERIFY_X509_STRICT is dropped.
    Some government sites (e.g. cpx.cbc.gov.tw) serve certs without a Subject Key Identifier."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def session(retries: int = 5, backoff: float = 2.0, ua: str = UA,
            non_strict_x509: bool = False) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        respect_retry_after_header=True,
    )
    adapter = _NonStrictX509Adapter if non_strict_x509 else HTTPAdapter
    s.mount("https://", adapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = ua
    return s


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def raw_path(source: str, name: str, year: int | str | None = None) -> Path:
    p = RAW / source / str(year) if year is not None else RAW / source
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def interim_path(name: str) -> Path:
    INTERIM.mkdir(parents=True, exist_ok=True)
    return INTERIM / name


def save_raw(source: str, name: str, content: bytes, url: str, year=None,
             rows: int | None = None, note: str = "") -> Path:
    """Write the response body untouched and log it to manifest.csv."""
    p = raw_path(source, name, year)
    p.write_bytes(content)
    log_manifest(source, url, p, sha256_bytes(content), rows, note)
    return p


def log_manifest(source: str, url: str, path: Path | str, sha: str,
                 rows: int | None = None, note: str = "") -> None:
    with _MANIFEST_LOCK:
        _append_manifest(source, url, path, sha, rows, note)


def _append_manifest(source, url, path, sha, rows, note) -> None:
    new = not MANIFEST.exists()
    with MANIFEST.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        rel = Path(path).resolve()
        try:
            rel = rel.relative_to(ROOT)
        except ValueError:
            pass
        w.writerow({
            "fetched_at_utc": now_utc(), "source": source, "url": url,
            "path": str(rel).replace("\\", "/"), "sha256": sha,
            "rows": "" if rows is None else rows, "note": note,
        })


def polite_sleep(seconds: float = 1.0) -> None:
    time.sleep(seconds)


def write_parquet_atomic(df, path: Path) -> None:
    """Write to a temp file then rename, so an interrupted run never corrupts an accumulated file."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
