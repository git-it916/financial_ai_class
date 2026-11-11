"""AI-1 반사실 모델, AI-2 변동성 예보 모델 → T7, T9, F4, F5, outputs/forecast_model.json.

analysis_spec.md를 커밋한 뒤에 처음 실행합니다.
"""
# %% 설정
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import fx24 as fx

panel = fx.load_panel()
p = panel[(panel.date >= fx.TRAIN_START) & ~panel.holiday_adjacent].reset_index(drop=True)


def ridge():
    return make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-2, 3, 20), cv=TimeSeriesSplit(5)))


def scores(y: pd.Series, yhat, bench) -> dict:
    """MAE, RMSE, 기준 예측 대비 R² (1 − 오차제곱합 / 기준의 오차제곱합)."""
    e, eb = y - yhat, y - bench
    return {"n": len(y), "MAE": e.abs().mean(), "RMSE": np.sqrt((e ** 2).mean()),
            "R2_vs_bench": 1 - (e ** 2).sum() / (eb ** 2).sum()}


def nw_mean(x) -> dict:
    """평균과 Newey–West(시차 5) 95% 신뢰구간·p값 (사양). p_small은 소표본 보정 + t분포로 다시 잰 p값."""
    y, one = np.asarray(x, float), np.ones(len(x))
    r = sm.OLS(y, one).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    small = sm.OLS(y, one).fit(cov_type="HAC", cov_kwds={"maxlags": 5, "use_correction": True}, use_t=True)
    lo, hi = r.conf_int()[0]
    return {"mean": r.params[0], "lo": lo, "hi": hi, "p": r.pvalues[0], "p_small": small.pvalues[0], "n": len(x)}


# %% AI-1 반사실: 글로벌 요인만으로 '전환이 없었다면'의 |r|. 원화 자신의 과거 변동성은 넣지 않는다.
X1 = ["ln_vix", "d_dollar_abs", "d_jpy_abs", "d_twd_abs", "d_us10y_abs", "monday"]
MODELS = {"baseline": DummyRegressor, "ridge": ridge,
          "tree": lambda: HistGradientBoostingRegressor(max_depth=2, max_iter=100, learning_rate=0.05,
                                                        random_state=0)}
pre = p[p.t < 0]


def oos(make) -> pd.Series:
    """학습 기간 안에서 확장 창 5겹: 각 겹의 시험 구간 예측을 이어 붙인다."""
    return pd.concat([
        pd.Series(make().fit(pre[X1].iloc[tr], pre.absr.iloc[tr]).predict(pre[X1].iloc[te]), index=pre.index[te])
        for tr, te in TimeSeriesSplit(5).split(pre)])


cv = {k: oos(m) for k, m in MODELS.items()}
t7m = pd.DataFrame({k: scores(pre.absr[v.index], v, cv["baseline"]) for k, v in cv.items()}).T
best = t7m.drop("baseline").MAE.idxmin()
use = best if t7m.at[best, "MAE"] < t7m.at["baseline", "MAE"] else "baseline"  # 기준선보다 나은 모델만
fx.save(t7m.assign(used=t7m.index == use), "T7_cf_models")
print(t7m.round(4), "\n반사실에 쓰는 모델:", use)


def cf(t0: int, n: int = fx.N_MAIN) -> pd.DataFrame:
    """t0 전까지 학습 → t0부터 n 거래일 예측. resid = 실제 − 예측."""
    tr, te = p[p.t < t0], p[(p.t >= t0) & (p.t < t0 + n)]
    pred = MODELS[use]().fit(tr[X1], tr.absr).predict(te[X1])
    return te.assign(pred=pred, resid=te.absr - pred)


post = cf(0)
placebo = pd.Series({t0: cf(t0).resid.mean() for t0 in fx.placebo_t0(panel)}, name="mean_resid")
eff = nw_mean(post.resid)
# 사후 추가 (2026-11-11): 전환 직전 60거래일도 같은 방법(그 전까지 학습)으로 예측한다.
# 모델이 전환 전부터 낮게 예측하고 있었다면 전환 후 잔차를 효과로 읽을 수 없으므로, 둘의 차이를 함께 보고한다.
pre60 = cf(-fx.N_MAIN)
assert pre60.t.max() < 0 <= post.t.min() and not pre60.post.any() and post.post.all()
both = pd.concat([pre60, post])
d = sm.OLS(both.resid, sm.add_constant(both.post.astype(float))).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
assert abs(d.params["post"] - (post.resid.mean() - pre60.resid.mean())) < 1e-9
d_lo, d_hi = d.conf_int().loc["post"]
eff = eff | {"model": use, "placebo_n": len(placebo),
             "placebo_share_abs_ge": (placebo.abs() >= abs(eff["mean"])).mean(),
             "pre60_mean": pre60.resid.mean(), "pre60_n": len(pre60),
             "diff": d.params["post"], "diff_lo": d_lo, "diff_hi": d_hi, "diff_p": d.pvalues["post"]}
fx.save(pd.DataFrame([eff]), "T7_cf_effect", index=False)
fx.save(placebo.rename_axis("t0").to_frame(), "T7_cf_placebo")
print(pd.DataFrame([eff]).round(4).T)

# %% 그림 F4 실제 vs 반사실 (20일 평균), F5 가짜 시행일 분포
s = p[p.t < fx.N_MAIN].assign(pred=MODELS[use]().fit(pre[X1], pre.absr).predict(p.loc[p.t < fx.N_MAIN, X1]))
# 20일 평균은 시행일을 넘겨서 내지 않는다 (전환 후 선은 20일째부터). 넘기면 전환 전 값이 음영에 섞인다.
a, b = (s.groupby(s.t >= 0)[c].transform(lambda x: x.rolling(20).mean()) for c in ("absr", "pred"))
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(s.date, a, label="actual |r| (20-day mean)")
ax.plot(s.date, b, label=f"counterfactual: {use} (20-day mean)")
ax.fill_between(s.date, a, b, where=s.t >= 0, alpha=0.2)
ax.axvline(pd.Timestamp(fx.REFORM), color="k", ls="--", lw=1)
ax.set(ylabel="|r| (%)")
ax.legend()
fig.savefig(fx.FIGS / "F4_counterfactual.png", dpi=150, bbox_inches="tight")

fig, ax = plt.subplots(figsize=(6, 4))
ax.hist(placebo, bins=12, alpha=0.7, label="placebo dates")
ax.axvline(eff["mean"], color="r", lw=2, label="2026-07-06")
ax.set(xlabel="mean(actual − counterfactual), next 60 days", ylabel="count")
ax.legend()
fig.savefig(fx.FIGS / "F5_placebo.png", dpi=150, bbox_inches="tight")

# %% AI-2 예보: 오늘 밤 미국 시장 시나리오 + 원화 최근 변동성(HAR) → 내일 15:30까지 |r|
X2 = ["ln_vix", "d_dollar_abs", "d_jpy_abs", "har_1", "har_5", "har_22"]
HAR = ["har_1", "har_5", "har_22"]
tr, te = p[p.t < 0], p[p.t >= 0]  # 전환 전 학습 → 전환 후 시험. 시험 자료로 다시 맞추지 않는다.
pred = {"HAR": LinearRegression().fit(tr[HAR], tr.absr).predict(te[HAR]),
        "ridge": ridge().fit(tr[X2], tr.absr).predict(te[X2])}
t9 = pd.DataFrame({k: scores(te.absr, v, te.har_22) for k, v in pred.items()}).T  # 기준: 최근 22일 평균
fx.save(t9, "T9_forecast")
print(t9.round(4))

# %% 배포: 자료 끝까지 전체로 다시 학습한 릿지 → outputs/forecast_model.json
model = ridge().fit(p[X2], p.absr)
sc, rg = model[0], model[-1]
last, recent = panel.iloc[-1], panel.absr.iloc[-22:]
q10, q90 = np.quantile(te.absr - pred["ridge"], [0.1, 0.9])
# 버그 수정 (2026-11-11): 패널 마지막 행의 VIX는 하루 전 미국 값이다. 기준일 다음 날 예보에 들어갈
# 값은 기준일 밤의 VIX이므로, 슬라이더 기본값은 원본의 최신 VIX로 둔다.
vix = pd.read_csv(fx.RAW / "fred_VIXCLS.csv", index_col=0, parse_dates=True).VIXCLS
vix = pd.to_numeric(vix, errors="coerce").dropna()
assert last.us_date <= vix.index[-1] <= last.date, f"최신 VIX 날짜 {vix.index[-1]:%Y-%m-%d}가 패널과 맞지 않음"
spec = {
    "asof": f"{last.date:%Y-%m-%d}", "features": X2,
    "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
    "coef": rg.coef_.tolist(), "intercept": float(rg.intercept_),
    "har": {"har_1": float(recent.iloc[-1]), "har_5": float(recent.iloc[-5:].mean()), "har_22": float(recent.mean())},
    "close_1530": float(last.close_1530), "vix_default": float(vix.iloc[-1]),
    "resid_q10": float(q10), "resid_q90": float(q90),
    "tiers": np.quantile(model.predict(p[X2]), [1 / 3, 2 / 3]).tolist(),
}


def predict_json(m: dict, vix: float, d_dollar: float, d_jpy: float) -> float:
    """페이지(JS)와 같은 식: ŷ = max(0, b0 + Σ w·(x − μ)/s). 변화는 %, 부호는 무시."""
    x = {"ln_vix": np.log(vix), "d_dollar_abs": abs(d_dollar), "d_jpy_abs": abs(d_jpy), **m["har"]}
    z = sum(c * (x[f] - mu) / sd for f, c, mu, sd in zip(m["features"], m["coef"], m["mean"], m["scale"]))
    return max(0.0, m["intercept"] + z)


def selftest(vix: float, d_dollar: float, d_jpy: float) -> dict:
    """JSON 식 = sklearn 예측인지 확인하고, 페이지가 같은 값을 내는지 볼 입력·정답을 돌려준다."""
    row = pd.DataFrame([{"ln_vix": np.log(vix), "d_dollar_abs": abs(d_dollar), "d_jpy_abs": abs(d_jpy),
                         **spec["har"]}])[X2]
    want = max(0.0, float(model.predict(row)[0]))
    assert abs(predict_json(spec, vix, d_dollar, d_jpy) - want) < 1e-9, (vix, d_dollar, d_jpy)
    return {"vix": vix, "d_dollar": d_dollar, "d_jpy": d_jpy, "expected": want}


spec = spec | {"selftest": [selftest(*c) for c in [(15, 0.0, 0.0), (25, 1.0, -1.5), (40, -2.0, 3.0)]]}
(fx.OUT / "forecast_model.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
print("forecast_model.json 저장, 자체 검증 3세트 통과")
