"""E1: are the measurement tools reliable? (docs/3_eda_plan.md 2, E1)

Value checks use pre-treatment data only (fx_date <= 2026-07-03). The one exception is the KRX
night-row date check, which needs the P2 ECOS 06:00 close and compares price levels, not the basis.
Outputs reports/tables/E1_*.csv and reports/figures/E1_*.png. python -m src.eda.e1_checks
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .e0_coverage import FIG, P, TAB, usable, windows

PRE_END = pd.Timestamp("2026-07-03")
P1L = (pd.Timestamp("2025-06-09"), PRE_END)
COLS = ["ccy", "ts_utc", "fx_date", "rate", "usd_notional", "expiry", "days", "tenor", "pb", "platform",
        "dup_group_size", "outlier", "bad_rate", "package", "session", "us_dst"]
R: dict[str, object] = {}  # headline numbers for the gate memo


def mad(s: pd.Series) -> float:
    return float((s - s.median()).abs().median())


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(TAB / f"E1_{name}.csv", index=False)


def krx_night_date(k: pd.DataFrame, d: pd.DataFrame) -> None:
    n = k[(k.session == "night") & k.is_front].set_index("bas_dd").close
    e = d.set_index("date").usdkrw_close
    p2 = n.loc["2026-07-06":"2026-10-09"]
    rows = []
    for lag, label in [(1, "ECOS close of D-1 (ends D 06:00)"), (0, "ECOS close of D"), (-1, "ECOS close of D+1")]:
        diff = (p2 - e.shift(lag).reindex(p2.index)).dropna()
        rows.append({"pairing": label, "n": len(diff), "median_won": round(diff.median(), 2), "mad_won": round(mad(diff), 2)})
    save(pd.DataFrame(rows), "krx_night_date")
    R["krx_night_date"] = rows


def pb_dups(t: pd.DataFrame) -> None:
    pre = t[t.fx_date <= PRE_END]
    g = pre.groupby(["ccy", "ts_utc", "rate", "usd_notional", "expiry"], observed=True)
    size = g.size()
    sizes = size.value_counts().sort_index().rename("groups").reset_index()
    sizes.columns = ["group_size", "groups"]
    save(sizes, "dup_group_sizes")
    two = pre[pre.dup_group_size == 2]
    mix = two.groupby(["ccy", "ts_utc", "rate", "usd_notional", "expiry"], observed=True).agg(
        pb_n=("pb", "sum"), platforms=("platform", "nunique"))
    pattern = mix.value_counts(normalize=True).rename("share").reset_index()
    save(pattern, "dup_pairs_pattern")
    R["dup_share_rows"] = round(float((pre.dup_group_size > 1).mean()), 4)
    R["dup_pairs_one_pb"] = round(float((mix.pb_n == 1).mean()), 4)
    R["dup_pairs_both_pb"] = round(float((mix.pb_n == 2).mean()), 4)
    R["dup_pairs_no_pb"] = round(float((mix.pb_n == 0).mean()), 4)
    R["dup_pairs_same_platform"] = round(float((mix.platforms == 1).mean()), 4)


def tenor(t: pd.DataFrame) -> None:
    k = t[(t.ccy == "KRW") & (t.fx_date <= PRE_END) & t.days.between(0, 400)]
    h = k.days.value_counts().sort_index()
    save(h.rename("trades").rename_axis("days").reset_index(), "krw_days_hist")
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.bar(h.index, h.values, width=1, color="#2c6fbb")
    for lo, hi in [(25, 40), (80, 100)]:
        ax.axvspan(lo - 0.5, hi + 0.5, color="#c0392b", alpha=0.12)
    ax.set_xlim(0, 200)
    ax.set_xlabel("days from trade date (KST) to expiry")
    ax.set_title("E1. KRW NDF trades by days to expiry, 2024-10 ~ 2026-07-03 (shaded: provisional 1M/3M buckets)", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "E1_krw_days.png", dpi=150)
    plt.close(fig)
    q = k.days.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    R["krw_days_quantiles"] = q.round(0).to_dict()
    R["krw_share_1M_bucket"] = round(float(k.days.between(25, 40).mean()), 4)
    R["krw_share_3M_bucket"] = round(float(k.days.between(80, 100).mean()), 4)
    R["krw_share_1M_wide_20_45"] = round(float(k.days.between(20, 45).mean()), 4)


def counts(t: pd.DataFrame) -> None:
    k = t[(t.ccy == "KRW") & (t.fx_date <= PRE_END)]
    k = k[usable(k)]
    w = windows(k)
    rows = []
    for name in ["w1530", "w1545", "w_close"]:
        per_day = k[w[name]].groupby("fx_date").size()
        for label, lo, hi in [("2024-10~2026-07-03", None, None), ("P1_late", *P1L)]:
            s = per_day if lo is None else per_day.loc[lo:hi]
            rows.append({"window": name, "sample": label, "days": len(s), "median": s.median(), "p10": s.quantile(0.1),
                         "min": s.min(), "share_days_lt20": round(float((s < 20).mean()), 4)})
    save(pd.DataFrame(rows), "krw_window_counts")
    R["window_counts"] = rows
    kst = k.ts_utc.dt.tz_convert("Asia/Seoul")
    slot = (kst.dt.hour * 2 + kst.dt.minute // 30)
    prof = k.groupby([slot.rename("slot"), k.us_dst.rename("us_dst")]).size() / k.fx_date.nunique()
    prof = prof.rename("trades_per_day").reset_index()
    prof["kst"] = prof.slot.map(lambda s: f"{s // 2:02d}:{30 * (s % 2):02d}")
    save(prof, "krw_slot_profile_pre")


def matched(t: pd.DataFrame, k: pd.DataFrame) -> None:
    front = k[(k.session == "day") & k.is_front][["fx_date", "settle_date"]].drop_duplicates("fx_date")
    x = t[(t.ccy == "KRW") & (t.fx_date >= P1L[0]) & (t.fx_date <= PRE_END)]
    x = x[~x.outlier & ~x.bad_rate & ~x.package].merge(front, on="fx_date", how="inner")
    x = x[(x.expiry - x.settle_date).dt.days.abs() <= 2]
    w = windows(x)
    rows = []
    for name in ["w_close", "w1545"]:
        per_day = x[w[name]].groupby("fx_date").size().reindex(front.fx_date[(front.fx_date >= P1L[0]) & (front.fx_date <= PRE_END)], fill_value=0)
        rows.append({"window": name, "days": len(per_day), "median": per_day.median(), "p25": per_day.quantile(0.25),
                     "share_days_ge10": round(float((per_day >= 10).mean()), 4), "share_days_zero": round(float((per_day == 0).mean()), 4)})
    save(pd.DataFrame(rows), "matched_maturity_counts")
    R["matched"] = rows


def krx_proxy(k: pd.DataFrame, d: pd.DataFrame) -> None:
    f = k[(k.session == "day") & k.is_front & k.close.notna()].set_index("fx_date")
    dd = d.set_index("date")
    x = f[["close", "days"]].join(dd[["usdkrw_close_1530", "swap_mid_1M", "swap_half_spread_1M"]], how="inner").dropna()
    x = x.loc[P1L[0]:PRE_END]
    # won per 30 days: KRX (15:45 close - 15:30 spot) scaled by days to settle; KMB 1M mid over ~30 days
    x["krx_pts_30d"] = (x.close - x.usdkrw_close_1530) / x.days * 30
    x["kmb_pts_30d"] = x.swap_mid_1M
    x["diff"] = x.krx_pts_30d - x.kmb_pts_30d
    out = {"n": len(x), "median_diff_won": round(x["diff"].median(), 3), "mad_diff_won": round(mad(x["diff"]), 3),
           "kmb_half_spread_med": round(x.swap_half_spread_1M.median(), 3),
           "corr_daily": round(x[["krx_pts_30d", "kmb_pts_30d"]].corr().iloc[0, 1], 3),
           "within_half_spread_share": round(float((x["diff"].abs() <= x.swap_half_spread_1M).mean()), 4)}
    save(pd.DataFrame([out]), "krx_proxy")
    R["krx_proxy"] = out
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(x.index, x.krx_pts_30d.rolling(5).median(), lw=1, label="KRX implied (5d median)")
    ax.plot(x.index, x.kmb_pts_30d, lw=1, label="KMB 1M mid")
    ax.set_ylabel("won per 30 days")
    ax.legend(fontsize=8)
    ax.set_title("F03 (E1). KRX-implied vs KMB 1M swap points, P1_late (pre-P2)", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "F03_krx_proxy.png", dpi=150)
    plt.close(fig)


def krx_night(k: pd.DataFrame) -> None:
    n = k[(k.session == "night") & k.is_front & (k.fx_date >= P1L[0]) & (k.fx_date <= PRE_END)]
    out = {"days": len(n), "zero_volume_share": round(float(n.close.isna().mean()), 4),
           "volume_median": float(n.volume.median()), "volume_p10": float(n.volume.quantile(0.1)),
           "range_median_won": round(float((n.high - n.low).median()), 2)}
    save(pd.DataFrame([out]), "krx_night_liquidity")
    R["krx_night"] = out


def news_time(t: pd.DataFrame) -> None:
    n = pd.read_parquet(P / "news_ndf.parquet")
    n = n[n.ny_date <= PRE_END]
    k = t[(t.ccy == "KRW") & (t.fx_date <= PRE_END)]
    k = k[usable(k)].copy()
    ny = k.ts_utc.dt.tz_convert("America/New_York")
    k["ny_date"] = ny.dt.tz_localize(None).dt.normalize()
    k["slot"] = ny.dt.hour * 2 + ny.dt.minute // 30
    med = k.groupby(["ny_date", "slot"]).rate.median().rename("dtcc").reset_index()
    x = med.merge(n[["ny_date", "ndf_1m"]], on="ny_date")
    x["absdiff"] = (x.dtcc - x.ndf_1m).abs()
    s = x.groupby("slot").agg(days=("absdiff", "size"), median_absdiff_won=("absdiff", "median")).reset_index()
    s["ny_time"] = s.slot.map(lambda v: f"{v // 2:02d}:{30 * (v % 2):02d}")
    s = s[s.days >= 0.5 * s.days.max()]
    save(s, "news_time_match")
    best = s.nsmallest(3, "median_absdiff_won")
    R["news_days_pre"] = int(n.ny_date.nunique())
    R["news_best_slots_ny"] = best[["ny_time", "median_absdiff_won", "days"]].to_dict("records")


def swap_source(d: pd.DataFrame) -> None:
    n = pd.read_parquet(P / "news_ndf.parquet")
    n = n[(n.ny_date <= PRE_END) & n.swap_1m_smb.notna()]
    dd = d.set_index("date")
    x = n.set_index("ny_date").join(dd[["swap_mid_1M", "swap_half_spread_1M"]], how="inner").dropna(subset=["swap_mid_1M"])
    x["diff"] = x.swap_mid_1M - x.swap_1m_smb
    out = {"n": len(x), "median_diff_won": round(x["diff"].median(), 3), "mad_diff_won": round(mad(x["diff"]), 3),
           "share_within_half_spread": round(float((x["diff"].abs() <= x.swap_half_spread_1M).mean()), 4),
           "corr": round(x[["swap_mid_1M", "swap_1m_smb"]].corr().iloc[0, 1], 3)}
    save(pd.DataFrame([out]), "swap_kmb_vs_smb")
    R["swap_source"] = out


def main() -> None:
    t = pd.read_parquet(P / "dtcc_ndf.parquet", columns=COLS)
    k = pd.read_parquet(P / "krx_usd.parquet")
    d = pd.read_parquet(P / "daily.parquet")
    for f in (lambda: krx_night_date(k, d), lambda: pb_dups(t), lambda: tenor(t), lambda: counts(t),
              lambda: matched(t, k), lambda: krx_proxy(k, d), lambda: krx_night(k), lambda: news_time(t),
              lambda: swap_source(d)):
        f()
    for key, v in R.items():
        print(f"{key}: {v}")


if __name__ == "__main__":
    main()
