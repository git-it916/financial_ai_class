"""Daily inputs (ECOS, KMB swap points, FRED, NY Fed) -> data/processed/daily.parquet, one row per date.

Dates are fx_dates: ECOS 'close' for D is the 02:00 (P1) / 06:00 (P2) close that ends fx_date D.
US series keep their US date; they are known at 17:00 ET that day, so a 15:30 KST measurement on
fx_date D may only use US values from D-1 (basis.py does that shift, not this file).
python -m src.clean.daily
"""
from __future__ import annotations

import pandas as pd

from ..collect.common import INTERIM, ROOT
from . import cleanlog
from .sessions import p1_late, period, us_dst_on

OUT = ROOT / "data" / "processed" / "daily.parquet"
TENORS = ["1M", "2M", "3M", "6M", "1Y"]


def ecos() -> pd.DataFrame:
    e = pd.read_parquet(INTERIM / "ecos_daily.parquet")
    w = e.pivot_table(index="date", columns="series", values="value")
    w.index = pd.to_datetime(w.index)
    w["close_late_kst"] = pd.Series("02:00", index=w.index).where(period(w.index.to_series()) != "P2", "06:00")
    w.loc[w.usdkrw_close.isna(), "close_late_kst"] = pd.NA
    # P2 changed open/high/low to the 06:00-06:00 day; flag so session-variance work can drop it
    w["ohl_24h_def"] = period(w.index.to_series()) == "P2"
    return w


def kmb_swap() -> pd.DataFrame:
    k = pd.read_parquet(INTERIM / "kmb_swap.parquet").set_index("date")
    k.index = pd.to_datetime(k.index)
    out = pd.DataFrame(index=k.index)
    for t in TENORS:  # source unit is jeon (1/100 won)
        out[f"swap_mid_{t}"] = (k[f"bid_{t}"] + k[f"offer_{t}"]) / 200
        out[f"swap_half_spread_{t}"] = (k[f"offer_{t}"] - k[f"bid_{t}"]) / 200
    return out


def us() -> pd.DataFrame:
    f = pd.read_parquet(INTERIM / "fred_daily.parquet").pivot_table(index="date", columns="series", values="value")
    f.index = pd.to_datetime(f.index)
    f.columns = [f"fred_{c}" for c in f.columns]
    return f


def build() -> pd.DataFrame:
    krx_days = pd.read_parquet(ROOT / "data" / "processed" / "krx_usd.parquet", columns=["bas_dd"]).bas_dd.unique()
    d = ecos().join(kmb_swap(), how="outer").join(us(), how="outer").sort_index()
    d.index.name = "date"
    d = d.reset_index()
    d["krx_open"] = d.date.isin(krx_days)
    d["kr_holiday"] = (d.date.dt.weekday < 5) & ~d.krx_open & (d.date <= max(krx_days))
    d["period"] = period(d.date)
    d["p1_late"] = p1_late(d.date)
    d["us_dst"] = us_dst_on(d.date)
    return d


def main() -> None:
    cleanlog.reset("daily")
    d = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(OUT, index=False)
    cleanlog.record("daily", "01_merge", "info", len(d), len(d),
                    "ECOS + KMB swap + FRED outer-joined on date; nothing dropped, gaps stay missing (no fill)", affected=0)
    for name, mask, why in [("ohl_24h_def", d.ohl_24h_def, "P2 ECOS open/high/low use the 06:00-06:00 day (not comparable to P1)"),
                            ("kr_holiday", d.kr_holiday, "weekday with KRX closed (Korean holiday)")]:
        cleanlog.record("daily", f"02_flag_{name}", "flag", len(d), len(d), why, affected=int(mask.sum()))
    cleanlog.record("daily", "99_saved", "info", len(d), len(d), f"saved {OUT.relative_to(ROOT)}", affected=0)
    print("saved", d.shape, "->", OUT.relative_to(ROOT), "|", d.date.min().date(), "~", d.date.max().date())
    cols = ["usdkrw_close_1530", "usdkrw_close", "usdkrw_mar", "swap_mid_1M", "cd_91d", "fred_DTB4WK", "fred_DTB3"]
    print(d.groupby("period", dropna=False)[cols].count())
    print("1M half-spread (won), median by period:", d.groupby("period").swap_half_spread_1M.median().to_dict())


if __name__ == "__main__":
    main()
