"""공용 상수와 함수. `python fx24.py`를 실행하면 합성 자료로 분절회귀를 점검합니다."""
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parent
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"
OUT = ROOT / "outputs"
TABLES, FIGS = OUT / "tables", OUT / "figures"
for _d in (RAW, PROC, TABLES, FIGS):
    _d.mkdir(parents=True, exist_ok=True)

START, END = "2022-12-01", "2026-10-30"   # 받는 기간 (재현 2023-01-02~, 자료 끝 2026-10-30)
REFORM = "2026-07-06"                     # 24시간 전환, t = 0
TRAIN_START = "2024-07-01"                # AI 학습 시작 (02시 마감 체제)
N_MAIN, N_ROBUST = 60, 40                 # 시행일 앞뒤 거래일 수
PLACEBO = ("2025-10-01", "2026-04-01", 5)  # 가짜 시행일: 기간과 거래일 간격
# 전환 후 한국 공휴일. ECOS는 이날도 15:30 종가를 내지만, 전환 전과 같은 달력을 쓰려고 거래일에서 뺀다.
# 출처: python holidays 0.108 (KR). 전환 전 공휴일은 ECOS에 행이 없다.
POST_HOLIDAYS = ["2026-07-17", "2026-08-17", "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09"]
CONTROLS = "ln_vix + dollar + spread + d_dollar_abs + monday"


def load_panel() -> pd.DataFrame:
    return pd.read_csv(PROC / "panel.csv", parse_dates=["date", "us_date"])


def save(df: pd.DataFrame, name: str, **kw) -> None:
    """표는 outputs/tables에만 쓴다. 엑셀에서 한글이 깨지지 않게 utf-8-sig."""
    df.to_csv(TABLES / f"{name}.csv", float_format="%.4f", encoding="utf-8-sig", **kw)


def window(p: pd.DataFrame, t0: int = 0, n: int = N_MAIN, donut: int = 0) -> pd.DataFrame:
    """t0 앞뒤 n 거래일. 공휴일을 낀 수익률은 빼고 t와 post를 t0 기준으로 다시 잰다.
    donut > 0이면 t0 앞 donut일과 t0부터 donut일을 뺀다."""
    w = p[(p.t >= t0 - n) & (p.t < t0 + n) & ~p.holiday_adjacent]
    t = w.t - t0
    w = w.assign(t=t, post=(t >= 0).astype(int))
    return w[(w.t < -donut) | (w.t >= donut)]


def its(w: pd.DataFrame, y: str = "absr"):
    """분절회귀 y = α + βt + τ·post + κ·t·post + γ'X + ε, Newey–West 시차 5."""
    return smf.ols(f"{y} ~ t + post + t:post + {CONTROLS}", data=w).fit(
        cov_type="HAC", cov_kwds={"maxlags": 5})


def its_row(res, w: pd.DataFrame, y: str, spec: str) -> dict:
    """보고용 한 줄: τ·κ와 95% 신뢰구간, n, 전환 전 평균 대비 τ(%)."""
    ci, pre = res.conf_int(), w.loc[w.post == 0, y].mean()
    return {"spec": spec, "y": y, "n": int(res.nobs),
            "tau": res.params["post"], "tau_lo": ci.at["post", 0], "tau_hi": ci.at["post", 1],
            "tau_p": res.pvalues["post"], "kappa": res.params["t:post"],
            "kappa_lo": ci.at["t:post", 0], "kappa_hi": ci.at["t:post", 1],
            "pre_mean": pre, "tau_pct_of_pre": 100 * res.params["post"] / pre}


def placebo_t0(p: pd.DataFrame) -> list[int]:
    """가짜 시행일들의 t (전체 패널 기준). 창 전체가 실제 시행일 전에 끝나야 한다."""
    lo, hi, step = PLACEBO
    ts = p.loc[(p.date >= lo) & (p.date <= hi), "t"]
    t0 = list(range(int(ts.min()), int(ts.max()) + 1, step))
    assert max(t0) + N_MAIN <= 0, "가짜 시행일 창이 실제 시행일과 겹침"
    return t0


if __name__ == "__main__":
    # 합성 자료: t = 0에서 |r| 수준이 0.15 뛴다. its()가 이 값을 되찾고,
    # 효과가 없는 가짜 시행일에서는 신뢰구간이 0을 포함해야 한다.
    rng = np.random.default_rng(0)
    n = 300
    t = np.arange(n) - 200
    fake = pd.DataFrame({
        "t": t, "holiday_adjacent": False, "monday": (t % 5 == 0).astype(int),
        "ln_vix": rng.normal(3, 0.2, n), "dollar": rng.normal(120, 2, n),
        "spread": rng.normal(-1, 0.2, n), "d_dollar_abs": np.abs(rng.normal(0, 0.3, n))})
    fake = fake.assign(absr=0.4 + 0.15 * (t >= 0) + 0.2 * (fake.ln_vix - 3) + np.abs(rng.normal(0, 0.3, n)))
    hit = its(window(fake)).conf_int().loc["post"]
    null = its(window(fake, t0=-120)).conf_int().loc["post"]
    assert hit[0] < 0.15 < hit[1], hit.tolist()
    assert null[0] < 0 < null[1], null.tolist()
    donut = window(fake, donut=5)
    assert len(window(fake)) == 2 * N_MAIN and len(donut) == 2 * N_MAIN - 10
    assert not donut.t.between(-5, 4).any()
    print("ok: 합성 효과 0.15 →", hit.round(3).tolist(), "/ 효과 없음 →", null.round(3).tolist())
