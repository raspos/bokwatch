# BOK워치 (BOK Watch)

한국은행 통화정책을 한 화면에서 보고하는 사내 대시보드. 세 축을 나란히 보여준다.

1. **모형 추정**: CD 91일 금리에서 역산한 금통위 회의별 금리 확률(25bp 격자 변환, 회의 배분 가정과 가능 범위 함께 표시)
2. **한은**: 통방문 문구 변화, 소수의견, 점도표, 발언, 의사록
3. **전문가·언론**: 증권사·IB 전망 컨센서스, 연합뉴스 '신현송' 기사
4. **정성 판단(AI)**: 네이버 뉴스 검색 API·연합뉴스 기사를 OpenAI 모델이 태깅·종합한 참고 지표
5. **경제지표·이벤트**: 미국 CPI·고용·FOMC 일정(자동), 미국·한국 CPI 실제치, 국내 지표 일정(수기)

정적 사이트(`site/`)와 빌드 단계에서 만든 JSON(`site/data/`)으로 구성한다. 브라우저는 같은 출처 JSON만 읽는다. d3 v7.9.0도 `site/vendor/`에 내장했다.

## 구조

```
bokwatch/model.py        확률 계산(순수 함수): 부트스트래핑·최소 인상 경로·lsq, 민감도
bokwatch/market.py       시장금리 → 모델 투입, 스냅샷·백테스트
bokwatch/fetch_rates.py  ECOS(722Y001 기준금리, 817Y002 시장금리), 수동 입력 CSV
bokwatch/fetch_news.py   연합뉴스 RSS 수집·필터 → site/data/news.jsonl
bokwatch/fetch_bok.py    한은 '통화정책방향 결정회의 일정 및 자료'(연도별 표)·의사록 목록 → site/data/minutes.json, 의사록 위원별 입장·소수의견
bokwatch/guidance.py     통방문 diff, 매파·비둘기 보조점수, 점도표 집계
bokwatch/reports.py      보고서 컨센서스
bokwatch/fetch_futures.py KRX Open API → KOFR 3개월 선물 정산가격 → data/futures.csv
bokwatch/futures_model.py KOFR 선물 → 회의별 확률(실험값)
bokwatch/fetch_events.py BLS(CPI·고용) 일정표+캘린더(ics)·연준(FOMC) 일정, FRED·ECOS CPI 실제치 → site/data/events.json
bokwatch/fetch_naver.py  네이버 뉴스 검색 API → site/data/naver.jsonl
bokwatch/ai_judge.py     OpenAI 기사 태깅(data/ai_tags.jsonl 캐시)·압력지수·종합 판단 → site/data/qual.json
bokwatch/memo.py         보고 메모 초안 + 문체 점검
build.py                 → site/data/{meta,guidance,reports,memo,backtest,minutes,news}.json, history.csv, snapshots/
data/config.yaml         일정·가정·ECOS 항목·RSS·한은 페이지·사전
data/reports.yaml        기관 전망(수기)
data/guidance.yaml       결정·표결·점도표·발언(수기)
data/statements/*.txt    통방문 원문
data/events.yaml         국내 지표 등 수기 이벤트
data/manual/*.csv        수동 금리 입력(ois_YYYY-MM-DD.csv, rates_YYYY-MM-DD.csv)
data/rates.csv           ECOS 누적(자동)
```

## 로컬 실행

```bash
pip install -r requirements.txt pytest
python -m pytest -q                         # 검산 포함 테스트
export ECOS_API_KEY=...                     # https://ecos.bok.or.kr/api
python -m bokwatch.fetch_rates --resolve    # 항목코드 확인 → config.yaml에 기록
python -m bokwatch.fetch_rates --full       # 2020-10부터 이력(정상 스프레드·백테스트용)
python -m bokwatch.fetch_bok
python -m bokwatch.fetch_news
python -m bokwatch.fetch_events
export NAVER_CLIENT_ID=... NAVER_CLIENT_SECRET=... OPENAI_API_KEY=...
python -m bokwatch.fetch_naver
python build.py
python -m bokwatch.ai_judge             # 태깅 + 종합 (--no-synth: 태깅·지수만)
python build.py
python -m http.server 8000 -d site          # http://localhost:8000
```

## PC에서 함께 작업하기

저장소가 기준점이다. PC, 클라우드 세션, 자동 갱신 봇이 모두 같은 GitHub 저장소를 주고받는다.

### 처음 한 번
```bash
git clone https://github.com/<계정>/joongang-bokwatch.git
cd joongang-bokwatch
python -m venv .venv
# Windows: .venv\Scripts\activate   /  macOS·Linux: source .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q
python build.py && python -m http.server 8000 -d site   # http://localhost:8000
```
API 키는 PC의 환경변수나 `.env` 파일에 둔다(`ECOS_API_KEY` 등). `.env.example`을 `.env`로 복사해 채우면 실행 때 자동으로 읽는다. `.env`는 `.gitignore`에 있어 커밋되지 않는다. 이미 설정된 환경변수가 우선한다. 저장소가 OneDrive 등 동기화 폴더 안에 있으면 `.env`도 클라우드에 올라가므로, 키 파일을 동기화 밖에 두고 `BOKWATCH_ENV_FILE`에 그 경로를 지정한다.

### 충돌을 피하는 규칙
- **봇 영역**(사람이 고치지 않는다): `site/data/**`, `data/rates.csv`, `data/ai_tags.jsonl`, `data/qual_history.csv`, `data/prob_log.csv`. 매일 10시 봇이 main에 커밋한다.
- **사람 영역**: `data/*.yaml`(전망·발언·일정·설정), `data/statements/`, `data/manual/`, 코드(`bokwatch/`, `site/*.js|css|html`).
- 작업 전에 항상 `git pull --rebase`를 한다. 커밋할 때는 사람 영역 파일만 `git add` 한다(`git add -A` 금지). 봇 영역이 충돌하면 원격 것을 택한다: `git checkout --theirs site/data && git add site/data`.
- **데이터만 고칠 때**(보고서 전망, 발언, 일정): main에 바로 커밋·푸시해도 된다. 다음 봇 실행 때 화면에 반영된다. 바로 반영하려면 Actions에서 `daily`를 수동 실행한다.
- **코드를 고칠 때**: 브랜치(`git switch -c 이름/작업`)에서 작업하고 PR로 합친다. `test.yml`이 테스트를 돌린다.
- 사람 여럿이 같은 YAML을 동시에 고치면 충돌이 난다. 고치기 전에 팀 채널에 파일 이름을 알린다.

## 자동 갱신 (하루 1회, 매일 10:00 KST)

`run_daily.py` 하나가 전부 돈다: 시장금리(ECOS) → KOFR 선물(KRX) → 한은 홈페이지 → 연합뉴스 RSS → 네이버 뉴스 → 지표 일정·실제치 → 빌드 → AI 태깅·종합 → 빌드·확률 기록.
단계가 실패하면 그 데이터원은 직전 값을 유지하고 화면 상단에 "갱신 실패(데이터원·원인·마지막 성공 시각)"를 띄운다.

| 실행 주체 | 설정 |
|---|---|
| Cloudflare 크론 `cron/`(주 실행) | 워커 `bokwatch-cron`이 09:40·10:30 KST에 `daily.yml`을 `workflow_dispatch`(skip_if_done=true)로 호출한다. 비밀 값 `GITHUB_TOKEN`(Actions 쓰기 권한)은 Cloudflare에만 둔다 |
| GitHub Actions `daily.yml`(보조) | 예약 cron 09:43·10:13 KST지만 실제로는 14:15~15:10 KST에 시작한다(4시간 넘게 지연). 오늘 기록이 있으면 건너뛴다. 끝나면 `_deploy.yml`로 배포 |
| PC 예약 작업 | Windows 작업 스케줄러가 매일 09:50에 `scripts/local_daily.ps1`(최신 코드 받기 → `run_daily.py` → 변경 커밋·푸시). 로그는 `%LOCALAPPDATA%okwatch`. 오늘 기록이 있으면 건너뛴다 |
| `test.yml` | push 때 테스트 |

- 시장금리는 10시 기준 직전 영업일 종가다(ECOS 일별 금리는 장 마감 뒤 반영).
- 미국 CPI(KST 밤 발표)는 다음 날 10시에 반영된다.
- 연합뉴스 RSS는 최근 기사만 주므로 하루 1회 수집으로는 일부만 잡힌다. 네이버 검색 API가 하루치를 보완한다.

### 날짜별 확률 기록
`build.py --log`(일일 실행의 마지막 단계)가 그날 화면에 낸 회의별 확률을 `data/prob_log.csv`에 한 줄씩 남긴다(기록일, 금리 기준일, 회의, 인상·동결·인하 확률, 기대금리, 투입 상품, 정상 스프레드). 같은 날 다시 돌리면 그날 줄만 바뀌고, 지난 기록은 고치지 않는다. 산출이 멈춘 날은 수치 없이 사유만 남긴다. 화면 '시장 확률' 탭의 '날짜별 확률 기록' 표가 이 파일을 보여 준다. '인상 확률 추이' 그래프는 과거 금리를 현재 가정으로 다시 계산한 값이라 기록과 다를 수 있다.

필요한 설정
- Secrets: `ECOS_API_KEY`, `KRX_API_KEY`(openapi.krx.co.kr → 선물 일별매매정보(주식선물外) 이용 신청), `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET`(console.ncloud.com → NAVER API HUB → Application 등록 → 검색 API의 Client ID·Secret), `OPENAI_API_KEY`. Cloudflare 배포면 `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`도 넣는다.
- Variables: `DEPLOY_TARGET` = `pages`(기본) 또는 `cloudflare`, `CF_PAGES_PROJECT`(선택)

## 배포 (Cloudflare Pages, 링크를 아는 누구나 열람)

2026-10-14 결정: Cloudflare Pages에 공개 배포하고 접근 제한(Cloudflare Access)은 두지 않는다. 상단 '사내 보고용' 띠는 끈다(`site.show_internal_banner: false`). 검색엔진 차단(`site/robots.txt`, `noindex`)은 유지해 링크로만 들어오게 한다.

1. Cloudflare → Workers & Pages → Create → Pages → Upload assets, 프로젝트 이름 `joongang-bokwatch`. 첫 배포는 `site` 폴더를 끌어다 놓는다.
2. 자동 배포: GitHub 저장소 Secrets에 `CLOUDFLARE_API_TOKEN`(권한 Account · Cloudflare Pages · Edit), `CLOUDFLARE_ACCOUNT_ID`, Variables에 `DEPLOY_TARGET=cloudflare`. 매일 10시 `daily.yml`이 갱신 뒤 `_deploy.yml`로 배포한다.
3. 접근을 다시 제한하려면 Zero Trust → Access → Applications에 Pages 도메인을 등록하고 허용 이메일 정책을 건다.

## 모델 요약 (자세한 내용은 화면 '방법·검증' 탭)

- 상품 i의 금리 y_i에서 정상 스프레드 s_i를 빼면, 결제일(기준일 다음 날)부터 만기까지의 평균 기대 기준금리가 된다고 본다. 금통위 결정은 회의 당일부터 적용한다.
- 짧은 만기부터 부트스트래핑한다. 한 만기 구간에 새 회의가 둘 이상이면 **최소 인상 경로**로 나눈다. 늦은 회의부터 0.25%p 격자 상한까지 채우고, 모자라면 격자를 한 단계 올린다. `method: lsq`를 고르면 `scipy.optimize.lsq_linear`로 비음수 최소제곱을 푼다.
- 확률: Δ_k가 0~25bp면 Δ/25bp. 25bp 이상이면 25bp 확정에 초과분을 50bp로 둔다. 음수는 인하로 대칭이다. 회의 뒤 수준 분포는 기대금리를 맞추는 인접 두 격자점 분포다.
- 정상 스프레드: `model.hold_windows`(기본 2023-02-24~2024-08-21, 3.50% 동결) 기간 y − 기준금리의 중앙값. 이력이 20일 미만이면 `spread_fallback`(CD 10bp)을 쓴다. `spread_override`로 덮어쓸 수 있다. −5bp·기본·+5bp를 모두 저장한다.
- 일정 밖 상품: `schedule_known_through`보다 만기가 길면 계산에서 뺀다. 2027년 일정이 미입력이라 현재는 CD 91일(만기 2027-01-13)까지만 쓴다.

### 검산 (tests/test_model.py)
입력: 기준일 2026-10-13, r0 3.00%, CD 91일 3.24%, 회의 10/22·11/26, 최소 인상 경로

| 스프레드 | 10월 인상 | 11월 인상 | 11월 뒤 3.25% |
|---|---|---|---|
| 10bp | 8.5% | 91.5% | 100% |
| 5bp | 60.5% | 39.5% | 100% |
| 15bp | 0.0% | 68.3% | 68.3% |

## 경제지표·이벤트

| 이벤트 | 일정 출처 | 실제치 |
|---|---|---|
| 미국 CPI | BLS 발표 일정표(자동), 08:30 ET → KST(서머타임 반영) | FRED CPIAUCNS·CPILFENS 전년동월비 |
| 미국 고용보고서 | BLS 발표 일정표(자동) | – |
| FOMC | 연준 일정표(자동), 둘째 날 14:00 ET 결정. `*`는 SEP(점도표) 회의 | – |
| 금통위·의사록 공개 | config·한은 연도별 회의 표·의사록 목록 | – |
| 한국 CPI·GDP·수출입 등 | `data/events.yaml` 수기 입력 | 한국 CPI는 ECOS 901Y009 전년동월비 |

- 한국 지표 공표일은 공식 공표일정 페이지의 구조를 확인하지 못해 자동 수집하지 않는다. 매달 초 `events.yaml`에 넣는다.
- 미국 CPI는 KST 밤(21:30·22:30)에 나온다. 실제치는 다음 날 10:00 일일 갱신 때 반영된다.

## 결정 예측 모형(실험)과 신호 기록

- `bokwatch/decision_model.py`: 2008~2026 정례회의(회의 1건 = 표본 1개)로 순서형 로지스틱을 학습하고, 그때까지의 회의로만 다음 회의를 맞히는 순차 검증을 한다. 입력은 회의 3영업일 전에 알 수 있던 값만(근원물가는 발표 시점 기준). 결과는 `site/data/decision.json`, 학습표는 `data/decision_dataset.csv`.
- 2026-10-15 결과: M1(CD−기준금리·CD 변화·근원물가 갭) Brier 0.3585, M2(+직전 변경 방향) 0.3498, 과거 결정 빈도 0.3541, 항상 동결 0.411 → 채택하지 않고 기록만 한다.
- AI 태그의 `signal`(추가 인상 신호·높은 금리 유지·이번 회의 동결 신호·인하 신호·중기 경로·배경 요인)을 사건 단위로 세어 `data/signal_history.csv`에 날짜별로 남긴다. 기록이 쌓이면 결정 예측 모형의 변수 후보로 순차 검증한다.

## AI 정성 판단

1. **수집**: 네이버 뉴스 **검색 API**로 `config.naver.queries` 키워드 기사를 받는다. 검색 결과 화면을 긁지 않으니 약관·차단 문제가 없다. 연합뉴스 RSS 기사도 함께 쓴다.
   - 저장은 제목·검색 요약·링크·시각까지만 한다. 본문은 받지 않는다.
   - 같은 제목을 다른 매체가 다시 보낸 기사는 하나로 묶고 매체 수만 기록한다.
2. **태깅**(매일 10시, 새 기사만): OpenAI 모델이 기사마다 관련성, 요인 10종, 방향(인상 압력/중립/인하 압력), 강도 1~3, 근거 한 줄을 붙인다.
   - 결과는 `data/ai_tags.jsonl`에 캐시해, 같은 기사는 다시 부르지 않는다.
   - 실행당 상한은 `ai.max_new_per_run`이다.
3. **압력지수**: Σ(방향×강도×중복보도 가중) ÷ Σ(강도×가중). 최근 72시간 관련 기사만 쓴다. 모델을 다시 부르지 않는 단순 합산이라 재현할 수 있다.
4. **종합 판단**(하루 1회): 기사 태그, 시장 확률, 점도표, 한은 발언, 지표를 함께 넣는다.
   - 다음 금통위 기준 방향(−2~+2), 근거 기사, 반대 근거, 시장과의 차이, 관전 포인트를 받는다.
   - 보고 메모에 '정성 판단(AI 자동 산출, 참고용)' 문단으로 들어간다.
5. **안전장치**
   - 기사 텍스트는 분류 대상 데이터로만 넘기고, 모델에 도구는 주지 않는다.
   - 구조화 출력(JSON 스키마)으로 형식을 고정한다.
   - 모델이 인용한 기사 id 중 입력에 없는 것은 버린다.
   - 모델이 거절(refusal)하거나 출력 한도에 걸리면 그 배치는 오류로 기록하고 직전 판단을 유지한다.
6. **모델·비용**: OpenAI Chat Completions 구조화 출력(JSON 스키마 strict)을 쓴다. 모델은 `config.ai.model`에 적는다(미지정이면 이 단계를 건너뛴다). 추론 모델이면 태깅 `reasoning_effort: low`, 종합 `medium`을 보낸다. 비용은 새 기사 수에 비례한다.

## 데이터 입력 요령

- **2027년 금통위 일정**: 한은 공지 후 `config.yaml` → `meetings."2027"`에 넣고 `schedule_known_through`를 고친다. 비어 있으면 화면에 경고 배지가 뜬다.
- **OIS**: `data/manual/ois_2026-10-14.csv` 형식(`id,rate,source`. id는 ois3m/ois6m/ois9m/ois1y). 그날 OIS가 있으면 CD 대신 OIS로 계산한다.
- **통방문 원문**: `data/statements/YYYY-MM-DD.txt`에 붙여넣고 `guidance.yaml`의 `statement_file`로 연결한다. 첫 줄이 `# … 임시본`이면 화면에 "원문 대조 필요"가 뜬다.
- **보고서·발언**: `reports.yaml`, `guidance.yaml`. 원문을 대조했으면 `verify: false`로 바꾸고 `link`를 넣는다.
- **의사록 공개일**: 규칙(회의일 + 14일 이후 첫 화요일. 2025-10~2026-08 회의 8건 실측과 일치)과 한은 공지가 다르면 `bok.minutes_release_override`에 `"회의일": "공개일"`로 넣는다.

## 한계

- CD 금리에는 은행 자금사정과 신용 프리미엄이 섞인다. OIS 데이터가 있을 때 가장 정확하다.
- 결과는 정상 스프레드 가정에 매우 민감하다. 현재 10월 회의는 ±5bp에 0%~60.5%를 오간다.
- 과거 결정 일자·금리(2021~2026.8), 2026년 5·7·8월 표결·점도표·통방문·성장률 전망은 2026-10-14 한은 원문(연도별 회의 표, 기준금리 추이, 공보, 의사록)과 대조했다. 기관 전망·발언은 아직 보도 인용이라 원문 대조가 필요하다.
- 매파·비둘기 점수와 의사록 견해 분류는 사전 기반 자동 산출로 참고용이다. 의사록은 위원을 익명으로 적는다.
- 연합뉴스·네이버 기사는 제목·시각·링크·요약만 저장·표시한다. 본문은 저장하지 않는다.
- AI 정성 판단은 제목·검색 요약만 보고 내린 자동 판단이다. 오분류·과대해석이 있을 수 있어 근거 기사 원문 확인이 필요하다. 검색 키워드 구성에 따라 판단이 기울 수 있다.
- BLS·연준·FRED는 2026-10-14 PC에서 실제 응답으로 확인했다. BLS는 `Accept`·`Accept-Language` 헤더가 없으면 403을 준다. BLS 일정표 페이지는 당일·지난 발표를 빼므로 캘린더(ics)로 보강한다. GitHub Actions(해외 IP)에서도 같은지는 첫 실행 로그로 확인한다.
- 한은 의사록 목록은 AJAX(`listCont.do`)로 오며 depth 파라미터가 없으면 전체 뉴스가 섞인다. 연도별 회의 표가 0건이면 "페이지 구조 변경 의심" 경고가 뜬다. 연합뉴스 RSS 두 피드는 2026-10-14 확인했다.
- ECOS 항목코드는 `--resolve`로 이름 매칭해 기록한다. 첫 실행 뒤 `config.yaml`에 들어간 코드와 이름을 한 번 확인한다.
