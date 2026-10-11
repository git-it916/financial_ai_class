# 인수인계: 데이터 수집 현황과 재개 방법

기준 시각: 2026-10-11 저녁 (KST). 연구 설계와 EDA 계획은 `plan.md.md`, 연구계획서는 `금인실_선행연구.docx`에 있습니다. 이 문서는 수집 단계를 다른 PC나 새 세션에서 이어가기 위한 메모입니다.

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
| KMB 스왑포인트 | `kmb swap` | 1M·2M·3M·6M·1Y BID/OFFER (단위 전) | 2023-10-12 ~ 수집 중 | `kmb_swap.parquet` |
| FOMC | `fomc` | 성명 발표일, KST 시각(서머타임 반영), 2020년 긴급회의 표시 | 2016 ~ 2027 | `fomc_meetings.parquet` |
| yfinance | `yf_intraday` | 5개 통화 1분봉(최근 30일)·5분봉·1시간봉(2년)·일봉 | 1분봉 2026-09-13 ~ | `yf_{1m,5m,1h,1d}.parquet` |
| DTCC | `dtcc` | NDF 등 외환 파생 체결 건별(5개 통화 행만 추림) | 2024-10-09 ~ 수집 중 | `data/external/` (OneDrive 동기화, git 제외) |
| GDELT | `gdelt` | 영문 기사 제목·시각, 4개 주제, 월별 최대 250건 | 2017-01 ~ 수집 중(매우 느림) | `gdelt_articles.parquet` |

- **원본 보관:** 원본 응답은 `data/raw/{출처}/`에 받은 그대로 두었습니다. 받은 파일마다 `manifest.csv`에 URL, 받은 시각, sha256, 행 수를 남겼습니다. ECOS 키는 `{KEY}`로 가려 기록합니다.
- **용량이 큰 자료:** DTCC 원본 zip과 일별 파일(약 1.1GB, 1,031개)은 `data/external/`에 있습니다. git에서는 빠지지만 OneDrive로 다른 PC에 넘어갑니다. 2026-10-11에 `~/fxbasis_data`에서 이리로 옮겼고, `manifest.csv` 경로도 함께 고쳤습니다. 위치를 바꾸려면 환경변수 `EXTERNAL_DATA_DIR`을 씁니다.

**중단 시점 (2026-10-11, 사용자가 작업 중지):**
- **DTCC:** 2024-10-09 ~ 2026-03-15까지 받았습니다. 그 구간에서도 평일 14일이 비어 있습니다(2025-05-28, 2025-12-03~05, 2026-01-22, 2026-02-04~16). 서버에 없는 날인지 일시 오류인지는 다시 돌리면 가려집니다. 2026-03-16 ~ 2026-10-09는 아직 받지 않았습니다. 그와 별도로 2021-03-19 하루치 파일이 있습니다.
- **KMB 스왑:** 2023-10-12 ~ 2026-01-23까지 받았습니다.
- **GDELT:** 저장된 것이 없습니다(처음부터).

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

`.env`에 넣습니다. 형식은 `.env.example`을 따르고, `.env`는 git에서 제외되어 있습니다. 2026-10-11 기준 이 PC의 `.env`는 비어 있고, 다른 프로젝트·환경변수에서도 키를 찾지 못했습니다.

| 키 | 발급 | 쓰는 수집기 |
| --- | --- | --- |
| `ECOS_API_KEY` | ecos.bok.or.kr/api → 인증키 신청 (즉시) | `ecos` |
| `KRX_API_KEY` | openapi.krx.co.kr → 인증키 신청 → '선물 일별매매정보' 이용 신청 (승인 1~2일) | `krx` |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | developers.naver.com → 애플리케이션 등록 → 검색 (즉시) | `naver` |
| `FRED_API_KEY` (선택) | fredaccount.stlouisfed.org | 발표일 달력용 |

## 4. 다른 PC에서 이어가기

1. **원래 PC에서 끄기 전에** 작업표시줄의 OneDrive 아이콘이 '최신 상태'인지 확인합니다. `data/external`의 1.1GB가 다 올라가야 합니다.
2. 새 PC에서 OneDrive 동기화가 끝났는지 확인합니다. 코드·설정·`.env`·`data/`(external 포함)·git 이력(`.git`)이 모두 이 폴더에 들어 있습니다. 파일 탐색기에서 `financial_ai_class` 폴더를 오른쪽 클릭 → **'항상 이 디바이스에 유지'**를 고르면 자료가 미리 내려받아져 수집기가 빨리 돕니다.
3. 가상환경을 새로 만듭니다(파이썬 3.14 기준, 3.11 이상이면 동작할 것으로 예상).
   ```
   python -m venv %USERPROFILE%\.venvs\fxbasis
   %USERPROFILE%\.venvs\fxbasis\Scripts\python -m pip install -r requirements.txt
   ```
4. 아래 재개 명령을 프로젝트 폴더에서 실행합니다. DTCC는 `data/external`에 있는 날짜를 건너뛰고 나머지만 받습니다. 새로 받을 필요가 없습니다.
5. Claude Code 대화 기록은 PC마다 따로 저장되어 넘어가지 않습니다. 새 PC에서는 프로젝트 폴더에서 `claude`를 실행하고 "HANDOFF.md 읽고 데이터 수집 이어서 해줘"라고 하면 됩니다.

## 5. 재개 명령

모두 프로젝트 루트에서 실행합니다. 이미 받은 부분은 건너뛰거나 이어서 받습니다. 중간 저장은 임시 파일에 쓴 뒤 이름을 바꾸는 방식이라, 종료 시점에 파일이 깨지지 않습니다.

```
set PY=%USERPROFILE%\.venvs\fxbasis\Scripts\python
set PYTHONIOENCODING=utf-8

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
