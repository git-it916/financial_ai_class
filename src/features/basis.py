"""Daily basis panel (KRW, 1M): one row per fx_date x method.

basis_bp = (F_ndf - F_on) / F_on * 365 / D * 1e4, with each NDF trade first moved to the onshore
maturity D using the KMB 1M swap points per day (rate + (D - d) * pts/D1M).

Methods
- krx_night: KRX night close (ends 06:00 KST) vs DTCC 1M trades in the `w` minutes before 06:00 KST
- krx_day:   KRX day close (15:45 KST) vs DTCC 1M trades within +-k minutes of 15:45
- dtcc_1530: ECOS 15:30 spot + KMB 1M mid (tenor D1M) vs DTCC 1M trades within +-k minutes of 15:30

`end` caps the fx_dates computed, so P2 is not even built before analysis_decisions.md says so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..clean.sessions import us_dst_on
from ..collect.common import ROOT

P = ROOT / "data" / "processed"
MIN_D = 15  # E2: days 10-14 to KRX settlement are ~1.6x noisier; next contract is too thin at night to roll early
W_NIGHT = 60  # E2: NDF window (minutes) before the 06:00 KST KRX night close
HALF_DAY = 5  # minutes either side of 15:30 / 15:45
D1M = 33  # ponytail: days from trade date to a standard 1M value date (spot T+2 + 1 month); median NDF 1M is 34
DTCC_COLS = ["ccy", "ts_utc", "fx_date", "rate", "days", "tenor", "outlier", "bad_rate", "package"]


def ndf_trades(end: pd.Timestamp, drop_outliers: bool = True) -> pd.DataFrame:
    t = pd.read_parquet(P / "dtcc_ndf.parquet", columns=DTCC_COLS)
    t = t[(t.ccy == "KRW") & (t.fx_date <= end)]
    t = t[t.tenor.eq("1M").fillna(False) & ~t.bad_rate & ~t.package & (~t.outlier if drop_outliers else True)]
    t = t.assign(ts_kst=t.ts_utc.dt.tz_convert("Asia/Seoul").dt.tz_localize(None))
    return t[["ts_kst", "fx_date", "rate", "days"]].reset_index(drop=True)


def _robust(g: pd.DataFrame) -> pd.Series:
    x = g.f_adj.to_numpy()
    med = np.median(x)
    sd = 1.4826 * np.median(np.abs(x - med))
    return pd.Series({"f_ndf": med, "n": len(x), "se_ndf": 1.2533 * sd / np.sqrt(len(x)) if len(x) > 1 else np.nan,
                      "last_min_before": g.min_before.min()})


def _window(t: pd.DataFrame, anchors: pd.DataFrame, before: int, after: int) -> pd.DataFrame:
    """anchors: columns anchor (KST naive timestamp), key, D, pts. Trades in [anchor-before, anchor+after]."""
    a = anchors.sort_values("anchor")
    x = pd.merge_asof(t.sort_values("ts_kst"), a, left_on="ts_kst", right_on="anchor", direction="nearest",
                      tolerance=pd.Timedelta(minutes=max(before, after)))
    x = x.dropna(subset=["anchor"])
    x["min_before"] = (x.anchor - x.ts_kst).dt.total_seconds() / 60
    x = x[(x.min_before <= before) & (x.min_before >= -after)]
    x["f_adj"] = x.rate + (x.D - x.days) * x.pts / D1M
    return x.groupby("key")[["f_adj", "min_before"]].apply(_robust)


def inputs(end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    k = pd.read_parquet(P / "krx_usd.parquet")
    k = k[k.is_front & k.close.notna() & (k.fx_date <= end) & (k.fx_date >= "2024-10-08")]
    d = pd.read_parquet(P / "daily.parquet").set_index("date")
    d = d[d.index <= end]
    return k, d


def krx_night(t: pd.DataFrame, k: pd.DataFrame, d: pd.DataFrame, w: int, anchor_hour: int = 6) -> pd.DataFrame:
    n = k[k.session == "night"].copy()
    # the session that starts on fx_date at 18:00 ends the next calendar morning; KRX dates it the next
    # trading day (bas_dd), which for Fridays/holidays is days later, so anchor on fx_date + 1 day
    end_day = n.fx_date + pd.Timedelta(days=1)
    n["anchor"] = end_day + pd.Timedelta(hours=anchor_hour)
    n["D"] = (n.settle_date - end_day).dt.days
    n["pts"] = n.fx_date.map(d.swap_mid_1M)
    n["key"] = n.fx_date
    nd = _window(t, n[["anchor", "key", "D", "pts"]].dropna(), before=w, after=0)
    out = n.set_index("key")[["close", "D"]].rename(columns={"close": "f_on"}).join(nd, how="inner")
    return out.assign(method="krx_night")


def krx_day(t: pd.DataFrame, k: pd.DataFrame, d: pd.DataFrame, half: int) -> pd.DataFrame:
    m = k[k.session == "day"].copy()
    m["anchor"] = m.fx_date + pd.Timedelta(hours=15, minutes=45)
    m["D"] = (m.settle_date - m.fx_date).dt.days
    m["pts"] = m.fx_date.map(d.swap_mid_1M)
    m["key"] = m.fx_date
    nd = _window(t, m[["anchor", "key", "D", "pts"]].dropna(), before=half, after=half)
    out = m.set_index("key")[["close", "D"]].rename(columns={"close": "f_on"}).join(nd, how="inner")
    return out.assign(method="krx_day")


def dtcc_1530(t: pd.DataFrame, d: pd.DataFrame, half: int) -> pd.DataFrame:
    x = d[["usdkrw_close_1530", "swap_mid_1M"]].dropna().copy()
    x["anchor"] = x.index + pd.Timedelta(hours=15, minutes=30)
    x["D"] = D1M
    x["pts"] = x.swap_mid_1M
    x["key"] = x.index
    nd = _window(t, x[["anchor", "key", "D", "pts"]], before=half, after=half)
    on = (x.usdkrw_close_1530 + x.swap_mid_1M).rename("f_on")
    out = pd.concat([on, x.D], axis=1).join(nd, how="inner")
    return out.assign(method="dtcc_1530")


def finish(p: pd.DataFrame) -> pd.DataFrame:
    p = p.rename_axis("fx_date").reset_index()
    p["basis_bp"] = (p.f_ndf - p.f_on) / p.f_on * 365 / p.D * 1e4
    p["se_ndf_bp"] = p.se_ndf / p.f_on * 365 / p.D * 1e4
    p["us_dst"] = us_dst_on(p.fx_date).to_numpy()
    return p


def build(end: pd.Timestamp, w_night: int = W_NIGHT, half_day: int = HALF_DAY) -> pd.DataFrame:
    t = ndf_trades(end)
    k, d = inputs(end)
    parts = [krx_night(t, k, d, w_night), krx_day(t, k, d, half_day), dtcc_1530(t, d, half_day)]
    p = finish(pd.concat(parts))
    p["main_sample"] = (p.D >= MIN_D) | (p.method == "dtcc_1530")
    return p


def path_b(p: pd.DataFrame) -> pd.DataFrame:
    """Main series (analysis_decisions.md v1): night basis minus the same-instrument day basis, same fx_date."""
    w = p[p.main_sample].pivot(index="fx_date", columns="method", values="basis_bp")
    out = (w.krx_night - w.krx_day).dropna().rename("path_b_bp").reset_index()
    out["us_dst"] = us_dst_on(out.fx_date).to_numpy()
    return out
