# 중앙 BOK워치 (JoongAng BOK Watch)

한국은행 통화정책을 한 화면에서 보고하는 사내 대시보드. 세 축을 나란히 보여준다.

1. **시장**: 시장금리에서 역산한 금통위 회의별 금리 확률(FedWatch 방식)
2. **한은**: 통방문 문구 변화, 소수의견, 점도표, 발언, 의사록
3. **전문가·언론**: 증권사·IB 전망 컨센서스, 연합뉴스 '신현송' 기사
4. **정성 판단(AI)**: 네이버 뉴스 검색 API·연합뉴스 기사를 Claude가 태깅·종합한 참고 지표
5. **경제지표·이벤트**: 미국 CPI·고용·FOMC 일정(자동), 미국·한국 CPI 실제치, 국내 지표 일정(수기)

정적 사이트(`site/`)와 빌드 단계에서 만든 JSON(`site/data/`)으로 구성한다. 브라우저는 같은 출처 JSON만 읽는다. d3 v7.9.0도 `site/vendor/`에 내장했다.

## 구조

```
bokwatch/model.py        확률 계산(순수 함수): 부트스트래핑·최소 인상 경로·lsq, 민감도
bokwatch/market.py       시장금리 → 모델 투입, 스냅샷·백테스트
bokwatch/fetch_rates.py  ECOS(722Y001 기준금리, 817Y002 시장금리), 수동 입력 CSV
bokwatch/fetch_news.py   연합뉴스 RSS 수집·필터 → site/data/news.jsonl
bokwatch/fetch_bok.py    한은 게시판(의사록·통화정책방향·간담회) → site/data/minutes.json, 의사록 PDF 키워드
bokwatch/guidance.py     통방문 diff, 매파·비둘기 보조점수, 점도표 집계
bokwatch/reports.py      보고서 컨센서스
bokwatch/fetch_events.py BLS(CPI·고용)·연준(FOMC) 일정, FRED·ECOS CPI 실제치 → site/data/events.json
bokwatch/fetch_naver.py  네이버 뉴스 검색 API → site/data/naver.jsonl
bokwatch/ai_judge.py     Claude 기사 태깅(data/ai_tags.jsonl 캐시)·압력지수·종합 판단 → site/data/qual.json
bokwatch/memo.py         보고 메모 초안 + 문체 점검
build.py                 → site/data/{meta,guidance,reports,memo,backtest,minutes,news}.json, history.csv, snapshots/
data/config.yaml         일정·가정·ECOS 항목·RSS·한은 게시판·사전
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
export NAVER_CLIENT_ID=... NAVER_CLIENT_SECRET=... ANTHROPIC_API_KEY=...
python -m bokwatch.fetch_naver
python build.py
python -m bokwatch.ai_judge             # 태깅 + 종합 (--no-synth: 태깅·지수만)
python build.py
python -m http.server 8000 -d site          # http://localhost:8000
```

## 자동 갱신 (GitHub Actions, KST 기준. cron은 UTC로 적음)

| 워크플로 | 시각 | 하는 일 |
|---|---|---|
| `daily.yml` | 평일 18:00 | ECOS·지표 → 확률·추이·백테스트 → AI 종합 판단 → 메모 |
| `news.yml` | 평일 07:00~22:00 매 30분 | 연합뉴스 RSS, 네이버 검색 API → 새 기사 AI 태깅·압력지수 |
| `bok.yml` | 매일 08:00·17:00 | 한은 의사록·결정문·간담회 새 글, 의사록 PDF 키워드, 지표 일정·실제치 |
| `_deploy.yml` | 위 셋이 끝난 뒤 호출 | GitHub Pages 또는 Cloudflare Pages 배포 |
| `test.yml` | push | 테스트 |

세 워크플로는 같은 `concurrency` 그룹으로 묶어 커밋 충돌을 막는다. 수집이 실패해도 빌드는 계속한다. 이 경우 직전 데이터를 유지하고, 화면 상단에 "갱신 실패(데이터원·원인·마지막 성공 시각)"를 띄운다.

필요한 설정
- Secrets: `ECOS_API_KEY`, `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET`(developers.naver.com → 애플리케이션 등록 → 검색 API), `ANTHROPIC_API_KEY`. Cloudflare 배포면 `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`도 넣는다.
- Variables: `DEPLOY_TARGET` = `pages`(기본) 또는 `cloudflare`, `CF_PAGES_PROJECT`(선택)

## 배포와 접근 제한

### A. GitHub Pages (비공개 저장소)
1. Settings → Pages → Source를 **GitHub Actions**로 둔다.
2. 접근 제한: GitHub Enterprise Cloud에서만 Pages 공개 범위를 **Private**(조직 구성원만)로 바꿀 수 있다. 그 외 요금제에서는 저장소가 비공개여도 **Pages 주소는 누구나 열 수 있다**. 이 경우 접근 제한이 없는 배포로 보고 아래를 유지한다.
   - `data/config.yaml`의 `site.show_internal_banner: true` → 상단에 "사내 보고용" 띠
   - `site/robots.txt`(전체 차단)와 `<meta name="robots" content="noindex">`로 검색엔진 차단

### B. Cloudflare Pages + Cloudflare Access (권장)
1. Cloudflare Pages 프로젝트 `joongang-bokwatch`를 만든다(Direct Upload). 저장소 변수는 `DEPLOY_TARGET=cloudflare`로 둔다.
2. Zero Trust → Access → Applications → Self-hosted에 Pages 도메인(`*.pages.dev`와 커스텀 도메인)을 등록한다.
3. Policy는 Allow, Include → Emails ending in → `@joongang.co.kr` 등 사내 도메인으로 둔다. 로그인 방식은 One-time PIN 또는 사내 IdP.
4. 프리뷰 배포 주소(`*.<project>.pages.dev`)도 같은 정책에 넣는다.
5. Access를 켠 뒤에는 `show_internal_banner: false`로 바꿔도 된다. robots 차단은 그대로 둔다.

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
| 금통위·의사록 공개 | config·한은 게시판 | – |
| 한국 CPI·GDP·수출입 등 | `data/events.yaml` 수기 입력 | 한국 CPI는 ECOS 901Y009 전년동월비 |

- 한국 지표 공표일은 공식 공표일정 페이지의 구조를 확인하지 못해 자동 수집하지 않는다. 매달 초 `events.yaml`에 넣는다.
- 미국 CPI는 KST 밤(21:30·22:30)에 나온다. 실제치는 다음 날 08:00 `bok.yml` 실행 때 반영된다.

## AI 정성 판단

1. **수집**: 네이버 뉴스 **검색 API**로 `config.naver.queries` 키워드 기사를 받는다. 검색 결과 화면을 긁지 않으니 약관·차단 문제가 없다. 연합뉴스 RSS 기사도 함께 쓴다.
   - 저장은 제목·검색 요약·링크·시각까지만 한다. 본문은 받지 않는다.
   - 같은 제목을 다른 매체가 다시 보낸 기사는 하나로 묶고 매체 수만 기록한다.
2. **태깅**(30분마다, 새 기사만): Claude가 기사마다 관련성, 요인 9종, 방향(인상 압력/중립/인하 압력), 강도 1~3, 근거 한 줄을 붙인다.
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
   - 모델이 거절하면 서버 측 fallback(`fallbacks: "default"`)으로 다른 모델이 다시 처리한다.
6. **모델·비용**: 기본은 `claude-opus-5-5`이고 `config.ai.model`에서 바꿀 수 있다. 태깅은 effort `low`, 종합은 `medium`이다. 비용은 새 기사 수에 비례한다.

## 데이터 입력 요령

- **2027년 금통위 일정**: 한은 공지 후 `config.yaml` → `meetings."2027"`에 넣고 `schedule_known_through`를 고친다. 비어 있으면 화면에 경고 배지가 뜬다.
- **OIS**: `data/manual/ois_2026-10-14.csv` 형식(`id,rate,source`. id는 ois3m/ois6m/ois9m/ois1y). 그날 OIS가 있으면 CD 대신 OIS로 계산한다.
- **통방문 원문**: `data/statements/YYYY-MM-DD.txt`에 붙여넣고 `guidance.yaml`의 `statement_file`로 연결한다. 첫 줄이 `# … 임시본`이면 화면에 "원문 대조 필요"가 뜬다.
- **보고서·발언**: `reports.yaml`, `guidance.yaml`. 원문을 대조했으면 `verify: false`로 바꾸고 `link`를 넣는다.
- **의사록 공개일**: 규칙(회의일 + 12일 이후 첫 화요일)과 한은 공지가 다르면 `bok.minutes_release_override`에 `"회의일": "공개일"`로 넣는다.

## 한계

- CD 금리에는 은행 자금사정과 신용 프리미엄이 섞인다. OIS 데이터가 있을 때 가장 정확하다.
- 결과는 정상 스프레드 가정에 매우 민감하다. 현재 10월 회의는 ±5bp에 0%~60.5%를 오간다.
- 보도 인용 초기값(전망·발언·점도표·통방문 문구·과거 결정 일자)은 원문 대조가 필요하다.
- 매파·비둘기 점수와 의사록 견해 분류는 사전 기반 자동 산출로 참고용이다. 의사록은 위원을 익명으로 적는다.
- 연합뉴스·네이버 기사는 제목·시각·링크·요약만 저장·표시한다. 본문은 저장하지 않는다.
- AI 정성 판단은 제목·검색 요약만 보고 내린 자동 판단이다. 오분류·과대해석이 있을 수 있어 근거 기사 원문 확인이 필요하다. 검색 키워드 구성에 따라 판단이 기울 수 있다.
- BLS·연준 페이지, 네이버 API, FRED는 개발 환경에서 접속하지 못해 샘플 HTML·JSON으로만 검증했다. 첫 Actions 실행 로그로 확인한다.
- 한은 게시판 주소(`bok.boards`)와 연합뉴스 RSS 주소는 개발 환경에서 접속을 못 해 확인하지 못했다. 첫 Actions 실행 로그로 확인한다. 게시물이 0건이면 "게시판 구조 변경 의심" 경고가 뜬다.
- ECOS 항목코드는 `--resolve`로 이름 매칭해 기록한다. 첫 실행 뒤 `config.yaml`에 들어간 코드와 이름을 한 번 확인한다.
