"""E0: coverage and quality (counts only, no basis values; P2 allowed).

Outputs: reports/figures/F01_coverage.png, reports/tables/T00_method_period.csv, T01_dictionary.csv,
T02_quality.csv. python -m src.eda.e0_coverage
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from ..clean.sessions import REGIMES, SAMPLE_END, us_dst_on
from ..collect.common import INTERIM, ROOT

P = ROOT / "data" / "processed"
TAB = ROOT / "reports" / "tables"
FIG = ROOT / "reports" / "figures"
START = pd.Timestamp("2016-01-01")
DTCC_COLS = ["ccy", "ts_utc", "fx_date", "tenor", "outlier", "bad_rate", "package"]
PERIODS = ["P_pre", "P0", "P1", "P1_late", "P2"]


def windows(t: pd.DataFrame) -> pd.DataFrame:
    """Time-window flags on DTCC trades: 15:30 / 15:45 KST +-5 min, and the 30 min before the NY 17:00 close."""
    kst = t.ts_utc.dt.tz_convert("Asia/Seoul")
    km = kst.dt.hour * 60 + kst.dt.minute + kst.dt.second / 60
    ny = t.ts_utc.dt.tz_convert("America/New_York")
    nm = ny.dt.hour * 60 + ny.dt.minute + ny.dt.second / 60
    return pd.DataFrame({
        "w1530": (km - (15 * 60 + 30)).abs() <= 5,
        "w1545": (km - (15 * 60 + 45)).abs() <= 5,
        "w_close": (nm >= 16 * 60 + 30) & (nm < 17 * 60),
    }, index=t.index)


def usable(t: pd.DataFrame) -> pd.Series:
    return t.tenor.eq("1M").fillna(False) & ~t.outlier & ~t.bad_rate & ~t.package


def load() -> dict[str, pd.Series]:
    """Each entry: the set of dates (as a Series of Timestamps) on which that input exists."""
    d = pd.read_parquet(P / "daily.parquet")
    k = pd.read_parquet(P / "krx_usd.parquet")
    t = pd.read_parquet(P / "dtcc_ndf.parquet", columns=DTCC_COLS)
    n = pd.read_parquet(P / "news_ndf.parquet")
    tw = pd.read_parquet(INTERIM / "cbc_tw_closing.parquet")
    bap = pd.read_parquet(INTERIM / "bap_usdphp.parquet")
    yf = pd.read_parquet(INTERIM / "yf_1m.parquet")
    kf = k[k.is_front & k.close.notna()]
    w = windows(t)
    ok = usable(t)
    krw = t[(t.ccy == "KRW")]
    s = {
        "ECOS 15:30 close": d.date[d.usdkrw_close_1530.notna()],
        "ECOS late close (02:00/06:00)": d.date[d.usdkrw_close.notna()],
        "ECOS MAR": d.date[d.usdkrw_mar.notna()],
        "KMB swap 1M": d.date[d.swap_mid_1M.notna()],
        "CD 91d": d.date[d.cd_91d.notna()],
        "FRED T-bill 4w": d.date[d.fred_DTB4WK.notna()],
        "KRX day close (front)": kf.fx_date[kf.session == "day"],
        "KRX night close (front)": kf.fx_date[kf.session == "night"],
        "DTCC KRW (any)": krw.fx_date,
        "DTCC KRW 1M 15:30+-5": t.fx_date[(t.ccy == "KRW") & ok & w.w1530],
        "DTCC KRW 1M pre-NY-close 30m": t.fx_date[(t.ccy == "KRW") & ok & w.w_close],
        "DTCC KRW 1M 15:45+-5": t.fx_date[(t.ccy == "KRW") & ok & w.w1545],
    }
    for c in ["TWD", "INR", "IDR", "PHP"]:
        s[f"DTCC {c} (any)"] = t.fx_date[t.ccy == c]
    s["News NDF 1M close"] = n.ny_date
    s["Taiwan CBC close"] = pd.to_datetime(tw.iloc[:, 0])
    s["Philippines BAP"] = pd.to_datetime(bap.iloc[:, 0])
    s["yfinance 1m"] = pd.to_datetime(yf.iloc[:, 0], utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None).dt.normalize()
    return {k_: pd.Series(pd.to_datetime(v).dt.normalize().unique()) for k_, v in s.items()}


def weekdays() -> pd.DatetimeIndex:
    return pd.bdate_range(START, SAMPLE_END)


def f01(sets: dict[str, pd.Series]) -> None:
    wd = weekdays()
    months = wd.to_period("M").unique()
    grid = pd.DataFrame({name: pd.Series(wd.isin(v), index=wd).groupby(wd.to_period("M")).mean()
                         for name, v in sets.items()}).reindex(months).T
    fig, ax = plt.subplots(figsize=(14, 0.38 * len(grid) + 1.5))
    ax.imshow(grid.to_numpy(dtype=float), aspect="auto", cmap="Blues", vmin=0, vmax=1, interpolation="nearest")
    ax.set_yticks(range(len(grid)), grid.index, fontsize=8)
    ticks = [i for i, m in enumerate(grid.columns) if m.month == 1]
    ax.set_xticks(ticks, [str(grid.columns[i].year) for i in ticks], fontsize=8)
    for name in ["P0", "P1", "P1_late", "P2"]:
        x = list(grid.columns).index(pd.Period(REGIMES[name]["start"], "M"))
        ax.axvline(x - 0.5, color="#c0392b", lw=0.8)
        ax.text(x, -0.8, name, color="#c0392b", fontsize=7, ha="left")
    ax.set_title("F01. Share of weekdays with data, by month (2016-01 ~ 2026-10-09)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "F01_coverage.png", dpi=150)
    plt.close(fig)


def period_masks(dates: pd.DatetimeIndex) -> dict[str, pd.Series]:
    s = pd.Series(dates, index=dates)
    out = {}
    for name in PERIODS:
        r = REGIMES[name]
        end = pd.Timestamp(r["end"]) if r.get("end") else SAMPLE_END
        out[name] = (s >= pd.Timestamp(r["start"])) & (s <= end)
    return out


def t00(sets: dict[str, pd.Series]) -> pd.DataFrame:
    """Days on which every input of a method exists, by period; DST-only counts for the main comparison."""
    wd = weekdays()
    has = {k: pd.Series(wd.isin(v), index=wd) for k, v in sets.items()}

    def prev(k: str) -> pd.Series:  # previous weekday
        return has[k].shift(1, fill_value=False)

    methods = {
        "dtcc_1530": has["DTCC KRW 1M 15:30+-5"] & has["ECOS 15:30 close"] & has["KMB swap 1M"],
        "krx_night_0600 (main)": has["KRX night close (front)"] & has["DTCC KRW 1M pre-NY-close 30m"],
        "krx_day_1545": has["KRX day close (front)"] & has["DTCC KRW 1M 15:45+-5"],
        "path_B (main, night & 15:30)": has["KRX night close (front)"] & has["DTCC KRW 1M pre-NY-close 30m"]
                                        & has["DTCC KRW 1M 15:30+-5"] & has["ECOS 15:30 close"] & has["KMB swap 1M"],
        "ecos_0600 (P2 only, check)": has["ECOS late close (02:00/06:00)"] & has["DTCC KRW 1M pre-NY-close 30m"],
        "news_approx": has["News NDF 1M close"] & prev("ECOS 15:30 close") & prev("KMB swap 1M"),
        "dtcc_activity (KRW & 4 controls)": has["DTCC KRW (any)"] & has["DTCC TWD (any)"] & has["DTCC INR (any)"]
                                            & has["DTCC IDR (any)"] & has["DTCC PHP (any)"],
    }
    dst = pd.Series(us_dst_on(pd.Series(wd)).to_numpy(), index=wd)
    pm = period_masks(wd)
    rows = []
    for m, ok in methods.items():
        row = {"method": m}
        for p, mask in pm.items():
            row[p] = int((ok & mask).sum())
            row[f"{p}_dst"] = int((ok & mask & dst).sum())
        rows.append(row)
    out = pd.DataFrame(rows)
    out.loc[len(out)] = {"method": "(weekdays in period)", **{p: int(m.sum()) for p, m in pm.items()},
                         **{f"{p}_dst": int((m & dst).sum()) for p, m in pm.items()}}
    out["P1_late_vs_P2_allowed"] = (out.P1_late_dst > 0) & (out.P2_dst > 0)
    # ECOS late close is 02:00 before P2 and 06:00 in P2: a different measurement, never compared across periods
    p2only = out.method.str.startswith("ecos_0600")
    out.loc[p2only, [c for c in out.columns if c.startswith(("P_pre", "P0", "P1")) and c != "P1_late_vs_P2_allowed"]] = 0
    out.loc[p2only | out.method.str.startswith("("), "P1_late_vs_P2_allowed"] = False
    return out


def t01_t02() -> tuple[pd.DataFrame, pd.DataFrame]:
    dic, q = [], []
    for f in ["daily", "krx_usd", "dtcc_ndf", "news_ndf"]:
        df = pd.read_parquet(P / f"{f}.parquet")
        for c in df.columns:
            ex = df[c].dropna()
            dic.append({"file": f, "column": c, "dtype": str(df[c].dtype), "non_null": round(df[c].notna().mean(), 4),
                        "example": str(ex.iloc[len(ex) // 2]) if len(ex) else ""})
        key = {"daily": ["date"], "krx_usd": ["fx_date", "session", "contract"], "dtcc_ndf": ["dissem_id"], "news_ndf": ["ny_date"]}[f]
        date = {"daily": "date", "krx_usd": "fx_date", "dtcc_ndf": "fx_date", "news_ndf": "ny_date"}[f]
        num = df.select_dtypes("number")
        # stale: a numeric column equal to its previous value, averaged over columns (daily-type files only)
        stale = (num.diff().eq(0).mean().mean()) if f in ("daily", "news_ndf") else None
        q.append({"file": f, "rows": len(df), "first": df[date].min().date(), "last": df[date].max().date(),
                  "dup_keys": int(df.duplicated(key).sum()), "stale_share": None if stale is None else round(float(stale), 4)})
    return pd.DataFrame(dic), pd.DataFrame(q)


def main() -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    sets = load()
    f01(sets)
    t = t00(sets)
    t.to_csv(TAB / "T00_method_period.csv", index=False)
    d, q = t01_t02()
    d.to_csv(TAB / "T01_dictionary.csv", index=False)
    q.to_csv(TAB / "T02_quality.csv", index=False)
    log = pd.read_csv(TAB / "cleaning_log.csv")
    print(t.to_string(index=False))
    print(q.to_string(index=False))
    print("cleaning log lines:", len(log))


if __name__ == "__main__":
    main()
