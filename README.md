# 24시간 외환시장과 원/달러 변동성

2026-07-06 원/달러 24시간 거래 전환이 일간 변동성을 키웠는지 분석하고, 같은 재료로 변동성 예보 모델을 만듭니다. 분석 사양은 [analysis_spec.md](analysis_spec.md)에, 전체 계획·선행연구·발표 자료는 `docs/`에 있습니다.

## 실행

1. `pip install -r requirements.txt`
2. `.env.example`을 `.env`로 복사하고 ECOS 인증키를 넣습니다.
3. VS Code에서 파일을 열고 ▷(Run Python File)를 누르거나, `# %%` 셀 단위로 순서대로 실행합니다.

| 파일 | 하는 일 | 만드는 것 |
|---|---|---|
| `01_data.py` | ECOS·FRED 받기 → 패널 → 검증 → 분석 0 재현 | `data/processed/panel.csv`, T4, excluded_days |
| `02_analysis.py` | 분석 1·2, 강건성, 시간대별 변동 | T3, T5, T6, T8, T10, F1, F2, F3, F6, F7, F8 |
| `03_ai.py` | AI-1 반사실, AI-2 예보 | T7, T9, F4, F5, `outputs/forecast_model.json` |

`02`와 `03`은 `analysis_spec.md`를 커밋한 뒤에 처음 돌립니다. 결과물은 모두 `outputs/`에 생깁니다. 공용 상수와 함수는 `fx24.py`에 있습니다.

## 검증

- `python fx24.py`: 합성 자료에 심은 효과를 분절회귀가 되찾는지 확인합니다.
- `01_data.py`는 다음을 확인하고, 하나라도 틀리면 그 자리에서 멈춥니다.
  - 스팟 체크 11개 값 (보도·강현주 수치로 날짜 귀속, 시가 시각, 고저가 창까지 확인)
  - 전환 후 공휴일 목록 (채권시장 휴장일과 대조)
  - 날짜 중복·평일 여부
  - 시가·종가가 그날 고저 안에 있는지
  - 끝 종가 날짜 귀속
  - 미래 정보 없음
  - 결측
  - 재현 ±10%
- `02`와 `03`은 가짜 시행일 창이 실제 시행일과 겹치지 않는지 확인합니다. `03`은 예보 JSON 식과 파이썬 예측이 같은지도 입력 3세트로 확인합니다.
- 논문 숫자는 `outputs/tables`에서만 복사합니다.

이전 주제(역내외 괴리)의 코드와 문서는 git 태그 `archive/ndf-basis`에 있습니다. 예를 들어 `git show archive/ndf-basis:analysis_decisions.md`로 볼 수 있습니다. 그때 받은 자료는 `data/_old/`에 있습니다.
