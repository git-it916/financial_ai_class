"""DTCC cumulative FX reports -> data/processed/dtcc_ndf.parquet (new NDF trades, 5 currencies vs USD).

Rules (docs/3_eda_plan.md 1.2): keep 'NA/Fwd NDF {CCY} USD' NEWT/TRAD rows; drop trades later
reported as EROR; apply the last CORR's rate/time/expiry/notional; dedupe on Dissemination Identifier.
Package, non-standard tenor, prime-brokerage duplicate groups and outliers are flagged, not dropped.
Every step is logged by cleanlog (reports/tables/cleaning_log.csv, data/processed/removed/).
python -m src.clean.dtcc
"""
from __future__ import annotations

import pandas as pd
from tqdm import tqdm

from ..collect.common import EXTERNAL, ROOT
from . import cleanlog
from .sessions import tag

SRC = EXTERNAL / "interim" / "dtcc"
OUT = ROOT / "data" / "processed" / "dtcc_ndf.parquet"
CCYS = ["KRW", "TWD", "INR", "IDR", "PHP"]
FISN = {f"NA/Fwd NDF {c} USD": c for c in CCYS}
COLS = ["file_date", "Dissemination Identifier", "Original Dissemination Identifier", "Action type", "Event type",
        "UPI FISN", "Execution Timestamp", "Expiration Date", "Exchange rate", "Notional amount-Leg 1",
        "Notional currency-Leg 1", "Notional amount-Leg 2", "Notional currency-Leg 2", "Platform identifier",
        "Prime brokerage transaction indicator", "Package indicator", "Non-standardized term indicator"]
CORR_FIELDS = ["Exchange rate", "Execution Timestamp", "Expiration Date", "Notional amount-Leg 1", "Notional amount-Leg 2"]
TENOR = {"1M": (25, 40), "3M": (80, 100)}  # ponytail: provisional buckets, fixed in E1 from the days histogram
MAD_K = 5
MIN_DEV = 4e-4  # ponytail: 5 x 4bp = 20bp floor (~1M p99 in-window spread); tuned in E2
REF_TOL = 0.10  # catches garbage/inverted quotes only; TWD fwd points and the 2025-05 surge exceed 3%
START = pd.Timestamp("2024-10-08")  # first file is 2024-10-09; older exec dates are late reports
SRC_NAME = "dtcc"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype("string").str.replace(r"[,+]", "", regex=True), errors="coerce")


def read_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    new, eror, corr, counts = [], [], [], []
    files = sorted(p for p in SRC.rglob("*.parquet") if p.stem >= "2024")
    skipped = sorted(p.name for p in SRC.rglob("*.parquet") if p.stem < "2024")
    for p in tqdm(files, desc="dtcc"):
        d = pd.read_parquet(p, columns=COLS)
        counts.append(d.assign(ndf=d["UPI FISN"].isin(FISN.keys()))
                      .groupby(["ndf", "Action type", "Event type"], dropna=False).size())
        d = d[d["UPI FISN"].isin(FISN.keys())]
        act = d["Action type"]
        eror.append(d.loc[act == "EROR", ["file_date", "Original Dissemination Identifier"]])
        corr.append(d.loc[act == "CORR", ["file_date", "Original Dissemination Identifier", *CORR_FIELDS]])
        new.append(d[(act == "NEWT") & (d["Event type"] == "TRAD")])
    c = pd.concat(counts).groupby(level=[0, 1, 2], dropna=False).sum().rename("rows").reset_index()
    total, ndf = int(c.rows.sum()), int(c[c.ndf].rows.sum())
    cleanlog.record(SRC_NAME, "00_files", "info", len(files), len(files),
                    f"read {len(files)} daily files; skipped old-layout files {skipped}", affected=0)
    cleanlog.record(SRC_NAME, "01_product", "drop", total, ndf,
                    "kept only 'NA/Fwd NDF {KRW,TWD,INR,IDR,PHP} USD' (other products, EUR crosses, NDS, options out)",
                    rows=c.astype({"Action type": "string", "Event type": "string"}))
    n = pd.concat(new, ignore_index=True)
    cleanlog.record(SRC_NAME, "02_newt_trad", "drop", ndf, len(n),
                    "kept Action type=NEWT & Event type=TRAD; lifecycle rows (TERM/CORR/MODI/EROR/COMP/NOVA/...) are "
                    "events on existing trades, counts by type in 01_product file", affected=ndf - len(n))
    return n, pd.concat(eror, ignore_index=True), pd.concat(corr, ignore_index=True)


def apply_corrections(n: pd.DataFrame, eror: pd.DataFrame, corr: pd.DataFrame) -> pd.DataFrame:
    before = len(n)
    dup = n["Dissemination Identifier"].duplicated(keep="last")
    cleanlog.record(SRC_NAME, "03_dedupe_id", "drop", before, before - int(dup.sum()),
                    "same Dissemination Identifier reported again (kept last)", rows=n[dup])
    n = n[~dup]
    gone = n["Dissemination Identifier"].isin(set(eror["Original Dissemination Identifier"]))
    cleanlog.record(SRC_NAME, "04_eror", "drop", len(n), len(n) - int(gone.sum()),
                    "trade later reported as EROR (cancelled as erroneous)", rows=n[gone])
    n = n[~gone].copy()

    last = (corr.sort_values("file_date").drop_duplicates("Original Dissemination Identifier", keep="last")
            .set_index("Original Dissemination Identifier"))
    hit = n["Dissemination Identifier"].isin(last.index)
    upd = last.loc[n.loc[hit, "Dissemination Identifier"], CORR_FIELDS]
    old = n.loc[hit, ["Dissemination Identifier", *CORR_FIELDS]].reset_index(drop=True)
    new = upd.reset_index(drop=True)
    diff = [old[["Dissemination Identifier"]].assign(field=f, old=old[f], new=new[f])[old[f].ne(new[f]).to_numpy()]
            for f in CORR_FIELDS]
    changes = pd.concat(diff, ignore_index=True)
    for f in CORR_FIELDS:
        n.loc[hit, f] = upd[f].to_numpy()
    cleanlog.record(SRC_NAME, "05_corr", "change", len(n), len(n),
                    f"applied last CORR to {int(hit.sum()):,} trades; only fields that actually changed are kept "
                    f"(by field: {changes.field.value_counts().to_dict()})",
                    rows=changes, affected=int(changes['Dissemination Identifier'].nunique()))
    return n


def shape(n: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(n["Execution Timestamp"], utc=True, errors="coerce")
    usd_leg1 = n["Notional currency-Leg 1"] == "USD"
    notional = n["Notional amount-Leg 1"].where(usd_leg1, n["Notional amount-Leg 2"]).astype("string")
    out = pd.DataFrame({
        "ccy": n["UPI FISN"].map(FISN).astype("category"),
        "ts_utc": ts,
        "rate": _num(n["Exchange rate"]),
        "usd_notional": _num(notional),
        "notional_capped": notional.str.endswith("+").fillna(False),
        "expiry": pd.to_datetime(n["Expiration Date"], errors="coerce"),
        "platform": n["Platform identifier"].astype("category"),
        "pb": n["Prime brokerage transaction indicator"] == "TRUE",
        "package": n["Package indicator"] == "TRUE",
        "nonstd": n["Non-standardized term indicator"] == "TRUE",
        "dissem_id": n["Dissemination Identifier"].astype("string"),
    }).reset_index(drop=True)
    bad = out.ts_utc.isna() | out.rate.isna()
    cleanlog.record(SRC_NAME, "06_unparseable", "drop", len(out), len(out) - int(bad.sum()),
                    "execution time or exchange rate could not be parsed", rows=out[bad])
    out = out[~bad].reset_index(drop=True)
    out = pd.concat([out, tag(out.ts_utc)], axis=1)
    early = out.fx_date < START
    cleanlog.record(SRC_NAME, "07_before_start", "drop", len(out), len(out) - int(early.sum()),
                    f"executed before {START.date()} (late reports of old trades; coverage starts with the 2024-10-09 file)",
                    rows=out[early])
    out = out[~early].reset_index(drop=True)
    out["days"] = (out.expiry - out.ts_kst.dt.tz_localize(None).dt.normalize()).dt.days
    out["tenor"] = pd.Series(pd.NA, index=out.index, dtype="string")
    for name, (lo, hi) in TENOR.items():
        out.loc[out.days.between(lo, hi), "tenor"] = name
    return out


def flag(t: pd.DataFrame) -> pd.DataFrame:
    key = ["ccy", "ts_utc", "rate", "usd_notional", "expiry"]
    t["dup_group_size"] = t.groupby(key, observed=True).rate.transform("size")
    win = [t.ccy, t.tenor.fillna("other"), t.ts_utc.dt.floor("10min")]
    med = t.groupby(win, observed=True).rate.transform("median")
    mad = (t.rate - med).abs().groupby(win, observed=True).transform("median")
    t["outlier"] = (t.rate - med).abs() > MAD_K * mad.clip(lower=med * MIN_DEV)
    d = pd.read_parquet(ROOT / "data" / "processed" / "daily.parquet").set_index("date").sort_index()
    ref = {"KRW": "usdkrw_mar", "TWD": "twd_per_usd", "INR": "inr_per_usd", "IDR": "idr_per_usd", "PHP": "php_per_usd"}
    t["bad_rate"] = False
    for c, col in ref.items():
        m = t.ccy == c
        r = d[col].dropna().reindex(t.loc[m, "fx_date"].unique(), method="ffill")
        t.loc[m, "bad_rate"] = ((t.loc[m, "rate"] / t.loc[m, "fx_date"].map(r) - 1).abs() > REF_TOL).fillna(False)
    flags = {
        "dup_group_size": (t.dup_group_size > 1, "same ccy/second/rate/notional/expiry appears more than once (PB double report?), judged in E1"),
        "outlier": (t.outlier, f"|rate - 10min median| > {MAD_K} x max(MAD, {MIN_DEV:.0e} x median) within ccy x tenor"),
        "bad_rate": (t.bad_rate, f"more than {REF_TOL:.0%} away from the ECOS daily reference rate"),
        "package": (t.package, "Package indicator = TRUE"),
        "nonstd": (t.nonstd, "Non-standardized term indicator = TRUE"),
        "notional_capped": (t.notional_capped, "notional reported as a cap ('+'); value is a lower bound"),
        "no_tenor": (t.tenor.isna(), f"maturity outside the 1M/3M buckets {TENOR}"),
    }
    for name, (mask, why) in flags.items():
        cleanlog.record(SRC_NAME, f"08_flag_{name}", "flag", len(t), len(t), why, affected=int(mask.sum()))
    return t


def main() -> None:
    cleanlog.reset(SRC_NAME)
    n, eror, corr = read_all()
    t = flag(shape(apply_corrections(n, eror, corr)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t.to_parquet(OUT, index=False)
    cleanlog.record(SRC_NAME, "99_saved", "info", len(t), len(t), f"saved {OUT.relative_to(ROOT)}", affected=0)


if __name__ == "__main__":
    main()
