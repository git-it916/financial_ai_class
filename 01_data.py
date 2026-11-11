"""자료 받기 → 패널 → 검증 → 분석 0(강현주 2026 재현).

VS Code에서 ▷로 통째로, 또는 `# %%` 셀 단위로 실행합니다.
원본은 data/raw에 받은 그대로 두고, 이미 있으면 다시 받지 않습니다 (새로 받으려면 파일을 지우세요).
"""
# %% 설정
import io
import json
import os
import urllib.request

import numpy as np
import pandas as pd
from dotenv import load_dotenv

import fx24 as fx

load_dotenv(fx.ROOT / ".env")
ECOS = {  # 이름: (통계표, 항목). 731Y003 = 원/달러 일별, 817Y002 = 시장금리 일별
    "open": ("731Y003", "0000002"),
    "close_1530": ("731Y003", "0000003"),
    "low": ("731Y003", "0000004"),
    "high": ("731Y003", "0000005"),
    "close_end": ("731Y003", "0000013"),  # 02:00(2024-07-01~) / 06:00(2026-07-06~) 종가
    "kr10y": ("817Y002", "010210000"),
}
FRED = {"vix": "VIXCLS", "dollar": "DTWEXBGS", "us10y": "DGS10", "jpy": "DEXJPUS", "twd": "DEXTAUS"}


def get(url: str, name: str, ok) -> bytes:
    """data/raw/name에 받은 그대로 저장하고 읽는다. 응답이 이상하면 저장하지 않고 멈춘다."""
    path = fx.RAW / name
    if not path.exists():
        body = urllib.request.urlopen(url, timeout=60).read()
        if not ok(body):
            raise RuntimeError(f"{name}: 예상과 다른 응답 {body[:200]!r}")
        path.write_bytes(body)
    return path.read_bytes()


def ecos(name: str, stat: str, item: str) -> pd.Series:
    key, s, e = os.getenv("ECOS_API_KEY", ""), fx.START.replace("-", ""), fx.END.replace("-", "")
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10000/{stat}/D/{s}/{e}/{item}"
    block = json.loads(get(url, f"ecos_{name}.json", lambda b: b'"StatisticSearch"' in b))["StatisticSearch"]
    assert int(block["list_total_count"]) == len(block["row"]), f"{name}: 한 번에 다 받지 못함"
    rows = pd.DataFrame(block["row"])
    return pd.Series(pd.to_numeric(rows.DATA_VALUE, errors="coerce").values,
                     index=pd.to_datetime(rows.TIME, format="%Y%m%d"), name=name)


def fred(name: str, sid: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={fx.START}&coed={fx.END}"
    body = get(url, f"fred_{sid}.csv", lambda b: b.startswith(b"observation_date"))
    df = pd.read_csv(io.BytesIO(body), index_col=0, parse_dates=True)
    return pd.to_numeric(df[sid], errors="coerce").rename(name)


def chg(x: pd.Series) -> pd.Series:
    """패널 행 사이 로그 변화(%)의 크기. r_t와 같은 거래일 간격이지만 시각은 반나절쯤 앞선다 (미국 날짜 t−2→t−1)."""
    return (100 * np.log(x).diff()).abs()


# %% 1. 받기
kr = pd.concat([ecos(n, *c) for n, c in ECOS.items()], axis=1, sort=True)
us = pd.concat([fred(n, s) for n, s in FRED.items()], axis=1, sort=True)
print(f"ECOS {kr.index.min():%Y-%m-%d}~{kr.index.max():%Y-%m-%d}, FRED {us.index.min():%Y-%m-%d}~{us.index.max():%Y-%m-%d}")

# %% 2. 패널
# 거래일 = 15:30 종가가 있는 날에서 전환 후 공휴일을 뺀 날 (전환 전과 같은 달력).
# 전환 후 공휴일 목록 점검: 채권시장이 쉬어 국고채 금리는 없는데 환율 종가는 고시된 날과 같아야 한다
closed = kr.index[kr.close_1530.notna() & kr.kr10y.isna() & (kr.index >= fx.REFORM)]
assert list(closed) == list(pd.to_datetime(fx.POST_HOLIDAYS)), f"전환 후 공휴일 목록이 자료와 다름: {closed.date}"
kr = kr.assign(kr10y=kr.kr10y.ffill())  # 국고채는 채권 영업일 기준이라 먼저 채운다
p = kr[kr.close_1530.notna() & ~kr.index.isin(pd.to_datetime(fx.POST_HOLIDAYS))]

# 한국 날짜 t ← 미국 날짜 t−1까지의 마지막 값 (그 미국 장은 한국 15:30 전에 끝남)
# 미국 휴일은 3영업일까지만 채운다. 더 묵은 값은 결측으로 남아 검증 (6)에서 걸린다.
us_t = us.ffill(limit=3).assign(us_date=us.index)
us_t.index = us_t.index + pd.Timedelta(days=1)
p = pd.merge_asof(p, us_t, left_index=True, right_index=True)

day = p.index.to_series()
r = 100 * np.log(p.close_1530).diff()
lag = r.abs().shift(1)
p = p.assign(
    r=r, absr=r.abs(),
    parkinson=100 * np.log(p.high / p.low) / np.sqrt(4 * np.log(2)),
    t=np.arange(len(p)) - p.index.get_loc(pd.Timestamp(fx.REFORM)),
    monday=(p.index.day_of_week == 0).astype(int),
    holiday_adjacent=day.shift(1) != day - pd.offsets.BDay(1),  # 직전 거래일 ≠ 직전 평일 → 공휴일을 낀 수익률
    ln_vix=np.log(p.vix),
    d_dollar_abs=chg(p.dollar), d_jpy_abs=chg(p.jpy), d_twd_abs=chg(p.twd),
    d_us10y_abs=p.us10y.diff().abs(),
    spread=p.kr10y.shift(1) - p.us10y,  # 국고 10년은 전 거래일 값
    har_1=lag, har_5=lag.rolling(5).mean(), har_22=lag.rolling(22).mean(),
)
p = p.assign(post=(p.t >= 0).astype(int))[[
    "close_1530", "r", "absr", "open", "high", "low", "close_end", "parkinson", "t", "post", "monday",
    "holiday_adjacent", "us_date", "ln_vix", "dollar", "d_dollar_abs", "spread", "d_jpy_abs", "d_twd_abs",
    "d_us10y_abs", "har_1", "har_5", "har_22"]]

# %% 3. 검증 — 하나라도 틀리면 여기서 멈춥니다
# (1) 스팟 체크: 보도·강현주(2026)의 숫자와 같아야 한다. 표 1의 정의(날짜 귀속, 시가 시각, 고저가 창)도 함께 확인한다.
SPOT = [("2024-07-01", "close_1530", 1379.3), ("2024-07-01", "close_end", 1383.8),  # 이투데이: 7/2 02:00 마감 → 7/1에 기록
        ("2024-07-31", "close_end", 1370.2),  # 연합인포맥스: 8/1 02:00 마감 → 7/31에 기록
        ("2024-12-03", "close_1530", 1402.9), ("2024-12-03", "close_end", 1425.0),  # 강현주·뉴시스
        ("2024-12-03", "high", 1442.0),  # 계엄 선포(22:27) 뒤 고점 → 고가에 야간 거래 포함
        ("2026-03-03", "close_1530", 1466.1), ("2026-03-03", "close_end", 1485.7),  # 강현주
        ("2026-07-06", "open", 1527.6),  # 헤럴드경제: 06:00 시작가 → 시가는 06:00
        ("2026-07-06", "close_end", 1530.0),  # 연합뉴스: 7/7 06:00 → 7/6에 기록
        ("2026-07-07", "close_1530", 1528.2)]  # 파이낸셜뉴스
for d, col, v in SPOT:
    got = p.at[pd.Timestamp(d), col]
    assert abs(got - v) < 0.05, f"스팟 체크 {d} {col}: {got} ≠ {v}"

# (2) 날짜: 중복 없음, 오름차순, 평일만
assert p.index.is_unique and p.index.is_monotonic_increasing and (p.index.day_of_week < 5).all()

# (3) 시가·15:30 종가·끝 종가가 그날 고저 안에 있어야 한다 (날짜 귀속이 같다는 증거)
for col in ["open", "close_1530", "close_end"]:
    out = p[(p[col] < p.low) | (p[col] > p.high)]
    assert out.empty, f"{col}이 고저 밖: {out.index.date[:5]}"

# (4) 끝 종가는 거래를 시작한 날짜에 기록된다 → 같은 날 시가보다 다음 날 시가와 가깝다
for a, b in [("2024-07-01", "2026-07-03"), (fx.REFORM, fx.END)]:
    x = p.loc[a:b]
    nxt = (x.close_end - x.open.shift(-1)).abs().median()
    same = (x.close_end - x.open).abs().median()
    print(f"끝 종가 {a}~ : 다음 날 시가와 {nxt:.1f}원, 같은 날 시가와 {same:.1f}원 (차이 중앙값)")
    assert nxt < same, "끝 종가 날짜 귀속이 예상과 다름"

# (5) 미래 정보 없음: 붙인 미국 값은 한국 날짜보다 앞선 날짜이고, 5일 넘게 묵지 않았다
lag_days = (day - p.us_date).dt.days.loc["2023-01-02":]
assert lag_days.between(1, 5).all(), lag_days.describe()

# (6) 분석 구간(2024-07-01~)에 결측 없음
need = ["absr", "parkinson", "close_end", "ln_vix", "dollar", "spread",
        "d_dollar_abs", "d_jpy_abs", "d_twd_abs", "d_us10y_abs", "har_22"]
miss = p.loc[fx.TRAIN_START:, need].isna().sum()
assert miss.sum() == 0, miss[miss > 0]

w = fx.window(p)
print(f"주 표본 {w.index.min():%Y-%m-%d}~{w.index.max():%Y-%m-%d}: 전 {(w.post == 0).sum()}일, 후 {(w.post == 1).sum()}일 "
      f"(공휴일 낀 수익률 {int(p.holiday_adjacent[(p.t >= -fx.N_MAIN) & (p.t < fx.N_MAIN)].sum())}일 제외)")

# %% 4. 저장
p.reset_index(names="date").to_csv(fx.PROC / "panel.csv", index=False)
excluded = pd.concat([
    pd.DataFrame({"date": pd.to_datetime(fx.POST_HOLIDAYS), "reason": "전환 후 공휴일 (거래일에서 뺌)"}),
    pd.DataFrame({"date": p.index[p.holiday_adjacent & (p.index >= "2023-01-02")],
                  "reason": "공휴일을 낀 수익률 (분석에서 뺌)"}),
]).sort_values("date")
fx.save(excluded, "excluded_days", index=False, date_format="%Y-%m-%d")
print(f"panel.csv {len(p)}행, 제외 목록 {len(excluded)}일")

# %% 5. 분석 0: 강현주(2026) 갭 변동성 재현 → T4 (데이터 처리 검증)
# Gap_t = |ln(O_t / C_{t−1})| × 100. C: 2024-07-01 전에는 15:30 종가, 이후에는 02:00 종가.
# 공휴일을 낀 갭은 뺀다 (분석 1과 같은 규칙). 보고서의 783일은 평일 수라서, 공휴일과 그 다음 날 갭이 결측으로 빠진 것과 같다.
# 모든 거래일을 쓰면 0.313 / 0.158 (+2.3% / +8.9%)로, 연휴를 건넌 큰 갭 때문에 높게 나온다.
prev = day.shift(1)
ext = prev >= "2024-07-01"
c_prev = p.close_end.shift(1).where(ext, p.close_1530.shift(1))
g = pd.DataFrame({"gap": (100 * np.log(p.open / c_prev)).abs(), "ext": ext})
g = g[~p.holiday_adjacent].loc["2023-01-02":"2025-12-31"]
t4 = g.groupby("ext").gap.agg(["mean", "count"]).set_axis(["연장 전", "연장 후"]).rename_axis("기간")
t4 = t4.assign(target=[0.306, 0.145], diff_pct=lambda d: 100 * (d["mean"] / d.target - 1))
fx.save(t4, "T4_replication")
print(t4.round(3))
assert (t4.diff_pct.abs() <= 10).all(), "재현 실패: 끝 종가 날짜 귀속부터 점검"
