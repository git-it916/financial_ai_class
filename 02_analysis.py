"""분석 1·2와 강건성 → T3, T5, T6, T8, F2, F3, F6.

analysis_spec.md를 커밋한 뒤에 처음 실행합니다 (결과를 보고 사양을 바꾸지 않기 위해).
"""
# %% 설정
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import fx24 as fx

p = fx.load_panel()
w = fx.window(p)
X = ["ln_vix", "dollar", "spread", "d_dollar_abs", "monday"]

# %% T3 기술통계 (주 표본, 전환 전 0 / 후 1)
t3 = w.groupby("post")[["absr", "parkinson", *X]].agg(["count", "mean", "std"]).T
fx.save(t3, "T3_descriptive")
print(t3.round(3))

# %% T5 분석 1: 일간 변동성 분절회귀
res = fx.its(w)
fx.save(res.summary2().tables[1], "T5_its")
main = fx.its_row(res, w, "absr", "주 표본 ±60")
print(f"τ = {main['tau']:.3f} [{main['tau_lo']:.3f}, {main['tau_hi']:.3f}], p = {main['tau_p']:.3f}, "
      f"n = {main['n']}, 전환 전 평균 대비 {main['tau_pct_of_pre']:.1f}%")
print(f"상식 점검: ln_vix 계수 {res.params['ln_vix']:+.3f} (양수여야 자연스러움)")

# %% T6 분석 2: 고저폭 vs 기계적 기대치
# 로그로 추정하면 τ가 곧 로그 증가율이다. 확률보행이면 측정 창 17→24시간에 τ = ln√(24/17) (+18.8%).
res2 = fx.its(w.assign(ln_park=np.log(w.parkinson)), "ln_park")
lo, hi = res2.conf_int().loc["post"]
mech = 0.5 * np.log(24 / 17)
verdict = ("새 시간대가 평균보다 조용" if hi < mech else
           "새벽이 변동성을 더함" if lo > mech else "기계적 기대치와 구별 안 됨")
t6 = pd.DataFrame([{"n": int(res2.nobs), "pct": 100 * np.expm1(res2.params["post"]),
                    "pct_lo": 100 * np.expm1(lo), "pct_hi": 100 * np.expm1(hi),
                    "mechanical_pct": 100 * np.expm1(mech), "verdict": verdict}])
fx.save(t6, "T6_parkinson", index=False)
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

# %% 그림 F2 환율과 일간 절대수익률, F3 분절회귀 적합선, F6 고저폭 추이
reform = pd.Timestamp(fx.REFORM)
s = p[p.date >= fx.TRAIN_START]

fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
a1.plot(s.date, s.close_1530, lw=1)
a1.set_ylabel("KRW/USD (15:30)")
a2.bar(s.date, s.absr, width=1)
a2.set_ylabel("|r| (%)")
for a in (a1, a2):
    a.axvline(reform, color="k", ls="--", lw=1)
fig.savefig(fx.FIGS / "F2_rate_absr.png", dpi=150, bbox_inches="tight")

grid = pd.DataFrame({"t": range(-fx.N_MAIN, fx.N_MAIN)}).assign(**w[X].mean())  # 통제변수는 표본 평균
grid = grid.assign(post=(grid.t >= 0).astype(int))
fig, ax = plt.subplots(figsize=(9, 4))
ax.scatter(w.t, w.absr, s=8, alpha=0.5)
for k in (0, 1):
    g = grid[grid.post == k]
    ax.plot(g.t, res.predict(g), lw=2)
ax.axvline(0, color="k", ls="--", lw=1)
ax.set(xlabel="trading days from 2026-07-06", ylabel="|r| (%)")
fig.savefig(fx.FIGS / "F3_its.png", dpi=150, bbox_inches="tight")

fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(s.date, s.parkinson, lw=0.5, alpha=0.5, label="daily Parkinson σ")
# 20일 평균은 시행일을 넘겨서 내지 않는다 (전환 후 선은 20일째부터). 넘기면 측정 창이 다른 값이 섞인다.
ax.plot(s.date, s.groupby(s.t >= 0).parkinson.transform(lambda x: x.rolling(20).mean()), lw=2, label="20-day mean")
ax.hlines(w.loc[w.post == 0, "parkinson"].mean() * np.sqrt(24 / 17), reform, s.date.max(),
          colors="r", ls=":", label="pre mean × √(24/17)")
ax.axvline(reform, color="k", ls="--", lw=1)
ax.set(ylabel="σ (%)")
ax.legend()
fig.savefig(fx.FIGS / "F6_parkinson.png", dpi=150, bbox_inches="tight")
