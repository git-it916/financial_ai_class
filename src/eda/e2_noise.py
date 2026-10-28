"""E2: noise floor and measurement choices, pre-treatment only (fx_date <= 2026-07-03, mostly P1_late).

Decides: NDF window before the 06:00 KRX close, minimum days to settlement (roll), whether the NDF
maturity adjustment works, path-B daytime leg, outlier-filter sensitivity, and the DST experiment (F02).
Outputs reports/tables/E2_*.csv, T04_noise_floor.csv, reports/figures/F02_dst.png.
python -m src.eda.e2_noise
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..features import basis as B
from .e0_coverage import FIG, TAB

END = pd.Timestamp("2026-07-03")
P1L = pd.Timestamp("2025-06-09")
STD = (pd.Timestamp("2025-11-03"), pd.Timestamp("2026-03-06"))  # P1_late standard-time block
KRX_TICK = 0.10
R: dict[str, object] = {}


def stats(s: pd.Series) -> dict:
    s = s.dropna()
    return {"days": len(s), "median": s.median(), "mad": (s - s.median()).abs().median(), "sd": s.std(),
            "sd_diff": s.diff().std(), "ac1": s.autocorr(1) if len(s) > 2 else np.nan}


def table(rows: list[dict], name: str) -> pd.DataFrame:
    df = pd.DataFrame(rows).round(2)
    df.to_csv(TAB / f"E2_{name}.csv", index=False)
    return df


def p1l(p: pd.DataFrame) -> pd.DataFrame:
    return p[(p.fx_date >= P1L) & (p.fx_date <= END)]


def window_choice(t, k, d, min_d: int) -> None:
    rows = []
    for w in [30, 60, 90, 120]:
        n = p1l(B.finish(B.krx_night(t, k, d, w)))
        n = n[n.D >= min_d]
        for label, m in [("dst", n.us_dst), ("all", n.us_dst | True)]:
            rows.append({"w_min": w, "sample": label, "n_trades_med": n[m].n.median(), "se_ndf_bp_med": n[m].se_ndf_bp.median(),
                         **stats(n[m].set_index("fx_date").basis_bp)})
    R["window"] = table(rows, "night_window")


def roll_floor(p: pd.DataFrame) -> None:
    rows = []
    for meth in ["krx_night", "krx_day"]:
        x = p1l(p[p.method == meth])
        x = x.assign(bucket=pd.cut(x.D, [0, 14, 19, 24, 60], labels=["10-14", "15-19", "20-24", "25+"]))
        for b, g in x.groupby("bucket", observed=True):
            rows.append({"method": meth, "days_to_settle": b, **stats(g.set_index("fx_date").basis_bp)})
    R["roll"] = table(rows, "roll_floor")


def maturity_adjustment(t, d) -> None:
    """Within the 15:30 window, slope of NDF rate on days vs the KMB-implied slope (pts per day)."""
    x = t[(t.fx_date >= P1L) & (t.fx_date <= END)].copy()
    m = x.ts_kst.dt.hour * 60 + x.ts_kst.dt.minute
    x = x[(m - (15 * 60 + 30)).abs() <= 10]
    rows = []
    for day, g in x.groupby("fx_date"):
        if g.days.nunique() < 3 or len(g) < 20:
            continue
        slope = np.polyfit(g.days, g.rate, 1)[0]
        rows.append({"fx_date": day, "slope_ndf": slope, "slope_kmb": d.swap_mid_1M.get(day, np.nan) / B.D1M})
    s = pd.DataFrame(rows).dropna()
    s.to_csv(TAB / "E2_maturity_slope.csv", index=False)
    R["maturity_slope"] = {"days": len(s), "median_ndf_won_per_day": round(s.slope_ndf.median(), 4),
                           "median_kmb_won_per_day": round(s.slope_kmb.median(), 4),
                           "corr": round(s[["slope_ndf", "slope_kmb"]].corr().iloc[0, 1], 3)}


def instruments(p: pd.DataFrame, min_d: int) -> None:
    """KRX day vs ECOS+KMB as the onshore leg, and the two path-B daytime legs."""
    w = p1l(p[(p.D >= min_d) | (p.method == "dtcc_1530")]).pivot(index="fx_date", columns="method", values="basis_bp")
    dst = p1l(p).drop_duplicates("fx_date").set_index("fx_date").us_dst.reindex(w.index)
    rows = []
    for label, m in [("dst", dst), ("all", dst | True)]:
        x = w[m.fillna(False)]
        rows += [{"series": "krx_day - dtcc_1530 (onshore instrument gap)", "sample": label, **stats(x.krx_day - x.dtcc_1530)},
                 {"series": "path B = night - krx_day", "sample": label, **stats(x.krx_night - x.krx_day)},
                 {"series": "path B = night - dtcc_1530", "sample": label, **stats(x.krx_night - x.dtcc_1530)},
                 {"series": "krx_night", "sample": label, **stats(x.krx_night)},
                 {"series": "krx_day", "sample": label, **stats(x.krx_day)},
                 {"series": "dtcc_1530", "sample": label, **stats(x.dtcc_1530)}]
    R["instruments"] = table(rows, "instruments_pathB")


def dst_experiment(t, k, d, w: int, min_d: int) -> None:
    rows, series = [], {}
    for hour, label in [(6, "window ends 06:00 KST (KRX close)"), (7, "window ends 07:00 KST (NY close in winter)")]:
        n = p1l(B.finish(B.krx_night(t, k, d, w, anchor_hour=hour)))
        n = n[(n.D >= min_d) & n.fx_date.between(*STD)].set_index("fx_date").basis_bp
        series[label] = n
        rows.append({"standard-time block": label, **stats(n)})
    n6 = p1l(B.finish(B.krx_night(t, k, d, w)))
    n6 = n6[n6.D >= min_d]
    rows.append({"standard-time block": "reference: DST days, ends 06:00", **stats(n6[n6.us_dst].set_index("fx_date").basis_bp)})
    R["dst"] = table(rows, "dst_experiment")
    fig, ax = plt.subplots(figsize=(9, 3.5))
    for label, s in series.items():
        ax.plot(s.index, s.values, lw=0.9, label=label)
    ax.axhline(0, color="#888", lw=0.5)
    ax.set_ylabel("night basis (bp, annualized)")
    ax.legend(fontsize=8)
    ax.set_title("F02. Standard-time block of P1_late: NDF window aligned to KRX close vs NY close", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "F02_dst.png", dpi=150)
    plt.close(fig)


def outlier_sensitivity(k, d, w: int, min_d: int) -> None:
    t_all = B.ndf_trades(END, drop_outliers=False)
    t = B.ndf_trades(END)
    a = p1l(B.finish(B.krx_night(t, k, d, w))).set_index("fx_date")
    b = p1l(B.finish(B.krx_night(t_all, k, d, w))).set_index("fx_date")
    diff = (a.basis_bp - b.basis_bp).dropna()
    R["outlier"] = {"days": len(diff), "median_abs_change_bp": round(diff.abs().median(), 2), "p95_abs_change_bp": round(diff.abs().quantile(0.95), 2)}


def noise_floor(p: pd.DataFrame, d: pd.DataFrame, min_d: int) -> None:
    rows = []
    for meth, g in p1l(p).groupby("method"):
        g = g[(g.D >= min_d) | (meth == "dtcc_1530")]
        to_bp = 365 / g.D / g.f_on * 1e4
        if meth == "dtcc_1530":
            onshore = (g.fx_date.map(d.swap_half_spread_1M) / np.sqrt(3) * to_bp).median()  # uniform within the quote
            src = "KMB half-spread / sqrt(3)"
        else:
            onshore = (KRX_TICK / np.sqrt(12) * to_bp).median()
            src = "KRX tick 0.10 / sqrt(12)"
        ndf = g.se_ndf_bp.median()
        total = np.sqrt(ndf ** 2 + onshore ** 2)
        mad_sd = 1.4826 * (g.basis_bp - g.basis_bp.median()).abs().median()
        rows.append({"method": meth, "ndf_se_bp": ndf, "onshore_noise_bp": onshore, "onshore_source": src,
                     "noise_total_bp": total, "basis_robust_sd_bp": mad_sd, "signal_to_noise": mad_sd / total})
    R["noise_floor"] = pd.DataFrame(rows).round(2)
    R["noise_floor"].to_csv(TAB / "T04_noise_floor.csv", index=False)


def main(w: int = 60, min_d: int = 15) -> None:
    t = B.ndf_trades(END)
    k, d = B.inputs(END)
    p = B.finish(pd.concat([B.krx_night(t, k, d, w), B.krx_day(t, k, d, 5), B.dtcc_1530(t, d, 5)]))
    window_choice(t, k, d, min_d)
    roll_floor(p)
    maturity_adjustment(t, d)
    instruments(p, min_d)
    dst_experiment(t, k, d, w, min_d)
    outlier_sensitivity(k, d, w, min_d)
    noise_floor(p, d, min_d)
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        for key, v in R.items():
            print(f"\n== {key}\n{v}")


if __name__ == "__main__":
    main()
