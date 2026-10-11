# 인수인계: 데이터 수집 현황과 재개 방법

기준 시각: 2026-10-11 밤 (KST, 두 번째 PC에서 이어받음). 연구 설계와 EDA 계획은 `plan.md.md`, 연구계획서는 `금인실_선행연구.docx`에 있습니다. 이 문서는 수집 단계를 다른 PC나 새 세션에서 이어가기 위한 메모입니다.

## 1. 지금까지 받은 것

| 출처 | 수집기 | 내용 | 기간 | 위치 |
| --- | --- | --- | --- | --- |
| FRED | `fred` | VIXCLS, DTWEXBGS, DGS2, DTB4WK, DTB3, DCPF3M, SOFR·30/90일 평균, DFF, DEXKOUS·DEXTAUS·DEXINUS | 2016-01 ~ 2026-10-09 | `data/interim/fred_daily.parquet` |
| 뉴욕연은 | `nyfed` | SOFR(분위수·거래량), EFFR | 2016-01(EFFR), 2018-04(SOFR) ~ | `nyfed_rates.parquet` |
| BIS | `bis` | 5개 통화 일별 환율(기간 평균), 정책금리 | 2016-01 ~ 2026-10-06 | `bis_xru_daily.parquet`, `bis_policy_rates.parquet` |
| CBOE | `cboe` | VIX 시가·고가·저가·종가 | 1990 ~ | `cboe_vix.parquet` |
| 대만 중앙은행 | `cbc_tw` | 대만달러 은행간 종가, 콜금리, 은행 고객 선물환율(일·월) | 2008(종가), 1991 ~ 2026-08 | `cbc_tw_*.parquet` |
| 필리핀 은행연합 | `bap` | 페소/달러 시가·고가·저가·종가, 오전·오후 가중평균, 거래량, 결제환율 | 2021-01 ~ | `bap_usdphp.parquet` |
| KMB 외환 | `kmb fx` | 매매기준율, 시가·고가·저가·종가, 총거래금액 | 2023-10-12 ~ (사이트 제공 한도) | `kmb_fx.parquet` |
| KMB 스왑포인트 | `kmb swap` | 1M·2M·3M·6M·1Y BID/OFFER (단위 전) | 2023-10-12 ~ 2026-10-09 (736일) | `kmb_swap.parquet` |
| FOMC | `fomc` | 성명 발표일, KST 시각(서머타임 반영), 2020년 긴급회의 표시 | 2016 ~ 2027 | `fomc_meetings.parquet` |
| yfinance | `yf_intraday` | 5개 통화 1분봉(최근 30일)·5분봉·1시간봉(2년)·일봉 | 1분봉 2026-09-13 ~ 10-09 (IDR은 685행으로 성김) | `yf_{1m,5m,1h,1d}.parquet` |
| DTCC | `dtcc` | NDF 등 외환 파생 체결 건별(5개 통화 행만 추림) | 2024-10-09 ~ 2026-10-10 (빠진 날 없음) + 2021-03-19 | `data/external/interim/dtcc/{YYYY}/` |
| GDELT | `gdelt` | 영문 기사 제목·시각, 4개 주제, 월별 최대 250건 | 2017-01 ~ 수집 중(매우 느림) | `gdelt_articles.parquet` |

- **원본 보관:** 원본 응답은 `data/raw/{출처}/`에 받은 그대로 두었습니다. 받은 파일마다 `manifest.csv`에 URL, 받은 시각, sha256, 행 수를 남겼습니다. ECOS 키는 `{KEY}`로 가려 기록합니다.
- **용량이 큰 자료:** DTCC 일별 파일(약 720MB)과 원본 zip은 프로젝트의 `data/external/`에 있습니다(OneDrive로 PC 간 동기화됨, git에서는 제외). 코드 기본값은 `~/fxbasis_data`이므로 **실행할 때 `EXTERNAL_DATA_DIR`를 `<프로젝트>/data/external`로 지정**합니다. 원본 zip은 2026-02-26 이후 일부만 있습니다(첫 PC의 zip은 넘어오지 않음).
- **동기화 주의:** 새 PC에서는 OneDrive가 일별 파일을 순서 없이 내려받습니다. 파일 수가 멈출 때까지 기다린 뒤 DTCC를 돌려야 충돌 사본이 생기지 않습니다.

**현황 (2026-10-11 밤, 두 번째 PC):**
- **DTCC:** 2024-10-09 ~ 2026-10-10 732일을 모두 받았습니다. 첫 PC에서 비었던 19일(2025-05-28, 2025-12-03~06, 2026-01-22, 2026-02-04~16)은 일시 오류였고, 다시 받아 채웠습니다. `dtcc_missing.csv`는 0건입니다. 이제부터는 매일 하루씩 받으면 됩니다.
- **KMB 스왑:** 2023-10-12 ~ 2026-10-09 완료.
- **yfinance:** 2026-10-11(일) 실행. 주말이라 1분봉에 새로 추가된 행은 없습니다. 평일에 다시 돌려야 누적됩니다.
- **GDELT:** 처음부터 받는 중입니다(2026-10-11 밤 시작, `data/external/gdelt_run.log`). 끊겨도 (주제, 월) 단위로 이어서 받습니다.
- **ECOS:** 14개 시리즈 2016-01-04 ~ 2026-10-09 완료. 항목 코드는 StatisticItemList로 검증. `ecos_daily.parquet`.
- **네이버:** 9,887건(2021-10 ~ 2026-10-11). `naver_news.parquet`. 매일 실행해 누적.
- **KRX:** 키는 있으나 모든 서비스에서 401(승인 대기 추정). 승인 후 `krx` 실행(이제 월별 중간 저장).
- **GDELT:** 이 IP가 429로 차단된 상태. 수집기를 고쳐 같은 달을 대기하며 재시도하고, 오래 막히면 저장 후 종료합니다. 다시 실행하면 이어 받습니다.

**데이터 점검 결과 (2026-10-11):** 중복 키 0, DTCC 733개 모두 읽힘.
- KMB 외환의 시가·고가·저가·종가는 **KMB 중개분만** 집계한 값입니다(MAR은 ECOS와 100% 일치). 시장 전체 OHLC는 ECOS를 씁니다.
- 원본 오기: BAP 2021-04-21·22(같은 행 반복, 저가>고가), 2021-05-20(시가 478.855), CBC 대만 2025-06-30 종가 29.902. 분석할 때 제외하거나 보정합니다.
- yfinance 일봉은 OHLC 논리 위반이 약 8%라 일별 분석에는 ECOS/KMB를 씁니다.

모든 파일은 정상입니다(파케이 메타데이터로 확인).

## 2. 수집하며 확인한 사실 (계획에 영향)

1. **DTCC는 최근 약 2년만 내려받을 수 있습니다.**
   - 2026-10-11 기준 첫 날짜는 2024-10-09이고, 매일 하루씩 사라집니다. 더 오래된 파일은 HEAD 요청에는 200을 주지만 GET은 403입니다.
   - 그래서 DTCC는 P0를 덮지 못하고, P1 중반(2024-10) 이후만 덮습니다.
   - 공식 PPD 사이트(pddata.dtcc.com)는 2026-10-11에 503이었습니다. 같은 파일을 DTCC 공개 S3(`kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/`)에서 받았습니다.
   - **매일 받는 자동 작업이 필요합니다.**
2. **KMB 스왑포인트와 외환은 약 3년치(2023-10 이후)만 제공됩니다.** P_pre·P0의 서울 스왑포인트는 단말기나 뉴스 기사에서 구해야 합니다. 스왑포인트 기간 조회 엑셀은 1Y만 주기 때문에, 전 만기는 날짜별 조회(느림)로 받습니다.
3. **KRX 정보데이터시스템(data.krx.co.kr)은 이제 로그인이 필요합니다.** 미국달러선물은 KRX Open API 키로만 받을 수 있습니다. 엔드포인트 `data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd`는 존재를 확인했습니다(키 없이 호출하면 401).
4. **FRED는 브라우저형 User-Agent를 지연시킵니다.** 기본 UA를 연구용 UA로 두었습니다. 대만 중앙은행 인증서는 파이썬 3.13 이상의 엄격한 X.509 검사에 걸리므로, 검증은 유지하고 엄격 플래그만 끈 어댑터를 씁니다.
5. **GDELT는 요청 제한(429)이 심합니다.** 2017년부터 전부 받으려면 하루 이상 걸릴 수 있어 우선순위를 가장 낮게 둡니다.
6. **수동으로 받아야 하는 것:**
   - 인도네시아 JISDOR: bi.go.id에서 기간을 지정해 엑셀로 받음
   - 인도 RBI 선물환 프리미엄, FBIL 기준환율
   - 필리핀 BAP 2021년 이전 자료: PDF로만 제공
   - BigKinds 뉴스 NDF 기사: 유료라 학술 협의 필요

## 3. 아직 필요한 키

`.env`에 넣습니다. 형식은 `.env.example`을 따르고, `.env`는 git에서 제외되어 있습니다. 2026-10-11 기준 두 PC 모두 키가 비어 있습니다(`.env`는 OneDrive로도 넘어오지 않았습니다).

| 키 | 발급 | 쓰는 수집기 |
| --- | --- | --- |
| `ECOS_API_KEY` | ecos.bok.or.kr/api → 인증키 신청 (즉시) | `ecos` |
| `KRX_API_KEY` | openapi.krx.co.kr → 인증키 신청 → '선물 일별매매정보' 이용 신청 (승인 1~2일) | `krx` |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | developers.naver.com → 애플리케이션 등록 → 검색 (즉시) | `naver` |
| `FRED_API_KEY` (선택) | fredaccount.stlouisfed.org | 발표일 달력용 |

## 4. 다른 PC에서 이어가기

1. OneDrive 동기화가 끝났는지 확인합니다(코드·설정·`data/interim`·`.env`가 넘어옴). git을 쓰려면 이 폴더에서 바로 작업하면 됩니다.
2. 가상환경을 새로 만듭니다(파이썬 3.14 기준, 3.11 이상이면 동작할 것으로 예상).
   ```
   python -m venv %USERPROFILE%\.venvs\fxbasis
   %USERPROFILE%\.venvs\fxbasis\Scripts\python -m pip install -r requirements.txt
   ```
3. DTCC 자료는 `data/external/interim/dtcc`로 OneDrive를 타고 넘어옵니다. 연도별 파일 수가 1분 넘게 그대로일 때까지 기다립니다. 빠진 날은 DTCC를 돌리면 채워지고, 2년 안의 자료는 서버에 있습니다.
4. 아래 재개 명령을 프로젝트 폴더에서 실행합니다.

## 5. 재개 명령

모두 프로젝트 루트에서 실행합니다. 이미 받은 부분은 건너뛰거나 이어서 받습니다. 중간 저장은 임시 파일에 쓴 뒤 이름을 바꾸는 방식이라, 종료 시점에 파일이 깨지지 않습니다.

```
set PY=%USERPROFILE%\.venvs\fxbasis\Scripts\python
set PYTHONIOENCODING=utf-8
set EXTERNAL_DATA_DIR=%CD%\data\external

%PY% -m src.collect.dtcc --workers 4          :: 기본 시작일 2024-10-09, 받은 날짜는 건너뜀(깨진 파일은 다시 받음)
%PY% -m src.collect.kmb swap --start 2023-10-12  :: kmb_swap.parquet에 있는 날짜는 건너뜀
%PY% -m src.collect.gdelt                      :: (주제, 월) 단위로 이어서 받음, 매월 저장
%PY% -m src.collect.yf_intraday                :: 매일 실행해 1분봉 누적
%PY% -m src.collect.ecos                       :: ECOS 키 필요
%PY% -m src.collect.krx                        :: KRX 키 + 서비스 승인 필요
%PY% -m src.collect.naver                      :: 네이버 키 필요, 매일 실행해 누적
```

한 번만 받으면 되는 것(다시 돌려도 됨): `fred`, `nyfed`, `bis`, `cboe`, `cbc_tw`, `bap`, `kmb fx`, `fomc`.

## 6. 다음 할 일

1. 키 발급 → `ecos`·`krx`·`naver` 실행. KRX 응답에서 야간 세션이 따로 구분되는지 먼저 확인합니다(`plan.md.md` 6.1).
2. 매일 수집 자동화: DTCC(2년 롤링), yfinance 1분봉(30일 롤링), 네이버(최근 1,100건). GitHub Actions 크론이나 Windows 작업 스케줄러를 씁니다.
3. 수동 자료(JISDOR, RBI·FBIL) 내려받기, 학교 단말기 이용 문의.
4. Gate 1 시작(`plan.md.md` 6.2): 측정방식×기간 가용표(T00), DTCC 정리(정정·취소, NDF 구분, 만기 분류), 잡음 하한표.
