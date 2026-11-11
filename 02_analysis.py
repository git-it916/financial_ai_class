"""분석 1·2와 강건성 → T3, T5, T6, T8, F2, F3, F6.

analysis_spec.md를 커밋한 뒤에 처음 실행합니다 (결과를 보고 사양을 바꾸지 않기 위해).
"""
# %% 설정
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
import pandas as pd

import fx24 as fx

p = fx.load_panel()
w = fx.window(p)
X = ["ln_vix", "dollar", "spread", "d_dollar_abs", "monday"]

# %% T3 기술통계 (주 표본, 전환 전 0 / 후 1)
t3 = w.groupby("post")[["r", "absr", "parkinson", *X]].agg(["count", "mean", "std"]).T
fx.save(t3, "T3_descriptive")
print(t3.round(3))

# %% T5 분석 1: 일간 변동성 분절회귀
res = fx.its(w)
fx.save(res.summary2().tables[1], "T5_its")
main = fx.its_row(res, w, "absr", "주 표본 ±60")
print(f"τ = {main['tau']:.3f} [{main['tau_lo']:.3f}, {main['tau_hi']:.3f}], p = {main['tau_p']:.3f}, "
      f"n = {main['n']}, 전환 전 평균 대비 {main['tau_pct_of_pre']:.1f}%")
print(f"상식 점검: ln_vix 계수 {res.params['ln_vix']:+.3f} (양수여야 자연스러움)")

# %% T10 (사후 추가) 전환 전 02시 마감 체제에서 하루 변동이 어느 시간대에 생겼나
# r_{t+1} = 야간 + 갭 + 주간. 24시간 전환이 새로 연 시간이 갭(02:00~09:00)이다.
q = p[(p.date >= fx.TRAIN_START) & (p.t < 0)]
nxt = q.shift(-1)
seg = 100 * pd.DataFrame({"night": np.log(q.close_end / q.close_1530),  # 15:30 → 02:00
                          "gap": np.log(nxt.open / q.close_end),         # 02:00 → 다음 날 09:00 (거래 없음)
                          "day": np.log(nxt.close_1530 / nxt.open)})     # 09:00 → 15:30
ok = nxt.holiday_adjacent.eq(False)                # 다음 거래일이 공휴일을 끼지 않은 날 (마지막 행도 빠짐)
weekday = (nxt.date - q.date).dt.days.eq(1)        # 갭은 주말을 끼지 않은 날만 (전환 후에도 주말에는 쉰다)
assert np.allclose(seg[ok].sum(axis=1), nxt.r[ok]), "세 구간의 합이 일간 수익률과 다름"
use = {"night": ok, "gap": ok & weekday, "day": ok}
ms = pd.Series({k: (seg.loc[m, k] ** 2).mean() for k, m in use.items()})
hours = pd.Series({"night": 10.5, "gap": 7.0, "day": 6.5})
t10 = pd.DataFrame({"hours": hours, "clock_share": hours / 24, "n": {k: int(m.sum()) for k, m in use.items()},
                    "mean_abs": {k: seg.loc[m, k].abs().mean() for k, m in use.items()},
                    "var_share": ms / ms.sum()}).rename_axis("segment")
fx.save(t10, "T10_time_of_day")
gap_share = t10.at["gap", "var_share"]
info = -0.5 * np.log(1 - gap_share)  # 시간대별 변동이 그대로일 때 고저폭의 로그 증가율
print(t10.round(3))
print(f"세 구간 제곱평균의 합 ÷ 일간 r² 평균 = {ms.sum() / (nxt.r[ok] ** 2).mean():.2f} (1이면 구간끼리 상관 없음)")

# %% T6 분석 2: 고저폭 vs 기계적 기대치
# 로그로 추정하면 τ가 곧 로그 증가율이다. 확률보행이면 측정 창 17→24시간에 τ = ln√(24/17) (+18.8%).
res2 = fx.its(w.assign(ln_park=np.log(w.parkinson)), "ln_park")
lo, hi = res2.conf_int().loc["post"]
mech = 0.5 * np.log(24 / 17)
verdict = ("새 시간대가 평균보다 조용" if hi < mech else
           "새벽이 변동성을 더함" if lo > mech else "기계적 기대치와 구별 안 됨")
t6 = pd.DataFrame([{"n": int(res2.nobs), "pct": 100 * np.expm1(res2.params["post"]),
                    "pct_lo": 100 * np.expm1(lo), "pct_hi": 100 * np.expm1(hi),
                    "mechanical_pct": 100 * np.expm1(mech), "verdict": verdict,
                    "info_weighted_pct": 100 * np.expm1(info)}])  # 사후 추가: 판정에는 쓰지 않는다
fx.save(t6, "T6_parkinson", index=False)
fx.save(res2.summary2().tables[1], "T6_its_parkinson")  # 논문 회귀표용 계수
print(t6.round(2).T)

# %% T8 강건성: 같은 회귀를 다른 표본·종속변수로 + 가짜 시행일
specs = {"±40": (fx.window(p, n=fx.N_ROBUST), "absr"),
         "시행일 앞뒤 5일 제외": (fx.window(p, donut=5), "absr"),
         "r²": (w.assign(r2=w.r ** 2), "r2")}
fits = {t0: fx.its(fx.window(p, t0)) for t0 in fx.placebo_t0(p)}
placebo = pd.DataFrame({"tau": {t0: r.params["post"] for t0, r in fits.items()},
                        "p": {t0: r.pvalues["post"] for t0, r in fits.items()}})
# 사후 추가 (2026-11-11): 효과가 없어야 할 가짜 시행일에서 p < 0.05가 5%보다 훨씬 자주 나와,
# Newey–West 신뢰구간이 실제보다 좁다. 그래서 가짜 τ의 분포와 HC3 표준오차를 함께 보고한다.
# 가짜 창은 서로 겹쳐서 24개가 독립은 아니다 (분위수는 대략적인 범위).
main = main | {"placebo_n": len(placebo),
               "placebo_share_abs_ge": (placebo.tau.abs() >= abs(main["tau"])).mean(),  # 가짜 |τ| ≥ 실제 |τ| 비율
               "placebo_q025": placebo.tau.quantile(0.025), "placebo_q975": placebo.tau.quantile(0.975),
               "placebo_reject_share": (placebo.p < 0.05).mean()}  # 정상이면 0.05 근처
hc3 = fx.its_row(fx.its(w, cov_type="HC3"), w, "absr", "주 표본 ±60 (HC3 표준오차)")
assert abs(hc3["tau"] - main["tau"]) < 1e-12, "표준오차만 바꿨는데 τ가 달라짐"
t8 = pd.DataFrame([main, hc3] + [fx.its_row(fx.its(d, y), d, y, k) for k, (d, y) in specs.items()])
fx.save(t8, "T8_robustness", index=False)
fx.save(placebo.rename_axis("t0"), "T8_placebo")
print(t8[["spec", "n", "tau", "tau_se", "tau_lo", "tau_hi", "tau_p", "mde_pct_of_pre"]].round(3))
print(f"가짜 시행일 {len(placebo)}개: τ 2.5~97.5% [{main['placebo_q025']:.3f}, {main['placebo_q975']:.3f}], "
      f"p < 0.05 비율 {main['placebo_reject_share']:.2f}, |τ| ≥ 실제 비율 {main['placebo_share_abs_ge']:.2f}")

# %% 그림 (양식은 fx24.py): F1 거래시간, F2 환율과 |r|, F3 분절회귀, F6 고저폭, F7 가짜 시행일, F8 시간대
reform = pd.Timestamp(fx.REFORM)
s = p[p.date >= fx.TRAIN_START]

# F1 거래시간 변천 (한국 시각, 06시~다음 날 06시). 색은 그 시간이 언제 열렸는지를 뜻한다.
regimes = [("Until June 2024", [(9, 15.5, fx.GRAY)]),
           ("July 2024 – July 3, 2026", [(9, 15.5, fx.GRAY), (15.5, 26, fx.BLUE)]),
           ("From July 6, 2026", [(6, 9, fx.RED), (9, 15.5, fx.GRAY), (15.5, 26, fx.BLUE), (26, 30, fx.RED)])]
fig, ax = plt.subplots(figsize=(6.5, 3.2))
for y, (_, parts) in enumerate(reversed(regimes)):
    for a, b, c in parts:
        ax.barh(y, b - a, left=a, color=c, height=0.5)
    ax.text(30.3, y, f"{sum(b - a for a, b, _ in parts):g} h", va="center")
ax.axvline(15.5, **fx.REFORM_LINE)  # 15:30 종가: 세 체제에서 정의가 같은 유일한 가격
ax.set_yticks(range(3), [name for name, _ in reversed(regimes)])
ax.set_xticks([6, 9, 12, 15.5, 18, 21, 26, 30],
              ["06:00", "09:00", "12:00", "15:30", "18:00", "21:00", "02:00", "06:00"])
ax.set(xlim=(6, 30), xlabel="Korea Standard Time")
fig.legend(handles=[Patch(color=fx.GRAY, label="Day session (09:00–15:30)"),
                    Patch(color=fx.BLUE, label="Opened in July 2024 (15:30–02:00)"),
                    Patch(color=fx.RED, label="Opened in July 2026 (02:00–09:00)")],
           loc="outside lower center", ncols=2)
fig.savefig(fx.FIGS / "F1_trading_hours.png")

fig, (a1, a2) = plt.subplots(2, 1, sharex=True)
a1.plot(s.date, s.close_1530, color=fx.BLUE, lw=1.2)
a1.set_ylabel("KRW/USD (15:30 close)")
a2.bar(s.date, s.absr, width=1, color=fx.BLUE)
a2.set_ylabel("|r| (%)")
for a in (a1, a2):
    a.axvline(reform, **fx.REFORM_LINE)
fig.savefig(fx.FIGS / "F2_rate_absr.png")

grid = pd.DataFrame({"t": range(-fx.N_MAIN, fx.N_MAIN)}).assign(**w[X].mean())  # 통제변수는 표본 평균
grid = grid.assign(post=(grid.t >= 0).astype(int))
fig, ax = plt.subplots()
ax.scatter(w.t, w.absr, s=10, color=fx.GRAY, alpha=0.7, label="Daily |r|")
for k, c, label in ((0, fx.BLUE, "Fitted, before the reform"), (1, fx.RED, "Fitted, after the reform")):
    g = grid[grid.post == k]
    ax.plot(g.t, res.predict(g), color=c, lw=2, label=label)
ax.axvline(0, **fx.REFORM_LINE)
ax.set(xlabel="Trading days from July 6, 2026", ylabel="|r| (%)")
fig.legend(loc="outside lower center", ncols=3)
fig.savefig(fx.FIGS / "F3_its.png")

pre_park = w.loc[w.post == 0, "parkinson"].mean()
fig, ax = plt.subplots()
ax.plot(s.date, s.parkinson, color=fx.GRAY, lw=0.5, alpha=0.7, label="Daily Parkinson volatility")
# 20일 평균은 시행일을 넘겨서 내지 않는다 (전환 후 선은 20일째부터). 넘기면 측정 창이 다른 값이 섞인다.
ax.plot(s.date, s.groupby(s.t >= 0).parkinson.transform(lambda x: x.rolling(20).mean()),
        color=fx.BLUE, lw=2, label="20-day mean")
ax.hlines(pre_park * np.exp(mech), reform, s.date.max(), colors=fx.RED, ls="--", lw=1.5,
          label=f"Time-proportional benchmark (+{100 * np.expm1(mech):.1f}%)")
ax.hlines(pre_park * np.exp(info), reform, s.date.max(), colors=fx.PURPLE, ls="-.", lw=1.5,
          label=f"Information-weighted benchmark (+{100 * np.expm1(info):.1f}%)")
ax.axvline(reform, **fx.REFORM_LINE)
ax.set(ylabel="Parkinson volatility (%)")
fig.legend(loc="outside lower center", ncols=2)
fig.savefig(fx.FIGS / "F6_parkinson.png")

# F7 가짜 시행일의 τ와 95% 신뢰구간 (Newey–West). 0을 벗어난 구간이 5%보다 훨씬 많다.
ci = np.array([r.conf_int().loc["post"] for r in fits.values()])
tau, sig, k = placebo.tau.values, (placebo.p < 0.05).values, np.arange(len(placebo))
fig, ax = plt.subplots()
for m, c, label in ((~sig, fx.BLUE, "Placebo date, not significant"), (sig, fx.RED, "Placebo date, p < 0.05")):
    ax.errorbar(k[m], tau[m], yerr=[tau[m] - ci[m, 0], ci[m, 1] - tau[m]], fmt="o", ms=4, lw=1, capsize=2,
                color=c, label=label)
ax.errorbar(len(k) + 1, main["tau"], yerr=[[main["tau"] - main["tau_lo"]], [main["tau_hi"] - main["tau"]]],
            fmt="D", ms=5, lw=1, capsize=2, color="k", label="Reform date (July 6, 2026)")
ax.axhline(0, color=fx.GRAY, lw=0.8)
dates = p.set_index("t").date.loc[placebo.index]
ax.set_xticks([*k[::4], len(k) + 1], [f"{d:%Y-%m}" for d in dates.iloc[::4]] + [f"{reform:%Y-%m}"], rotation=30)
ax.set(xlabel="Break date", ylabel="Estimated level shift (%p)")
fig.legend(loc="outside lower center", ncols=2)
fig.savefig(fx.FIGS / "F7_placebo_its.png")

# F8 전환 전 시간대별 비중: 시계로 본 비중과 가격 변동(제곱평균)으로 본 비중
order = ["night", "gap", "day"]
fig, ax = plt.subplots()
for dx, col, c, label in ((-0.2, "clock_share", fx.GRAY, "Share of clock time"),
                          (0.2, "var_share", fx.BLUE, "Share of daily return variance")):
    ax.bar_label(ax.bar(np.arange(3) + dx, 100 * t10.loc[order, col], 0.4, color=c, label=label), fmt="%.0f%%")
ax.set_xticks(range(3), ["Night session, 15:30–02:00\n(opened in July 2024)",
                         "Closed hours, 02:00–09:00\n(opened in July 2026)", "Day session, 09:00–15:30"])
ax.set(ylabel="Share (%)")
fig.legend(loc="outside lower center", ncols=2)
fig.savefig(fx.FIGS / "F8_time_of_day.png")
