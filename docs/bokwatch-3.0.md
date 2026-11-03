# BOK WATCH 3.0 개발 기록 (브랜치 `bokwatch-3.0`, 미배포)

## 구현됨
| 영역 | 내용 | 파일 |
|---|---|---|
| 뉴스 화이트리스트 | 허용 38곳, 도메인은 실제 페이지에서 확인한 것만 등록, 출처 판정(포털 링크는 원출처 확인 불가로 제외) | `data/press.yaml`, `data/press_verified.json`, `bokwatch/press.py`, `press_verify.py` |
| 기사 중복 | 재수집·통신사 전재·제목 변경·수정은 가장 먼저 나온 기사만, 같은 사건·독립 보도는 보존 | `bokwatch/dedupe.py` |
| 정성평가 | 허용 기사 중 중복을 뺀 것만 태깅·점수, 근거 유형(직접발언·전문가해석·기자분석·사실전달) 분류 | `bokwatch/ai_judge.py` |
| 뉴스 지표 | 관심도·방향성·논조 변화·정책 신호 강도, 주요 매파·비둘기파 신호, 제외 사유 | `bokwatch/news_metrics.py` |
| 한은 발언 | 같은 행사 통합, 논조·이전 대비 변화·주제별 신호·표현 변화 | `bokwatch/speech_events.py` |
| 통방문 | 범주별 핵심 변화(상위 5개), 가능한 의미(규칙표, 단정 아님) | `bokwatch/statement_changes.py` |
| 기관 전망 | 수집 현황, 30·7·1일 전 방향 적중률, BOK WATCH 같은 시점 비교, 순위 게이트(5회 미만 생략) | `bokwatch/forecast_eval.py` |
| 확률 변화 | 다음 회의 확률 그래프(7·30·90일·전체), 큰 변화일(5%p) 탐지와 동시 발생 이벤트 상세 | `bokwatch/prob_events.py`, `site/app.js` |
| BOK LAB | 금리 데이터 구분, ACM·AFNS 진행 상태, 모형 변경 이력 | `bokwatch/lab_status.py`, `data/model_changelog.yaml` |
| 정보구조 | 탭 막대에 BOK WATCH / BOK INTELLIGENCE / BOK LAB 영역 표시(기존 탭·주소 유지) | `site/index.html` |

## 구현하지 않음·한계
- 본문 기반 평가: 저장소 원칙("기사는 제목·요약·링크만 저장")과 충돌해 제목·요약 기반(저신뢰)으로 유지
- ACM·AFNS 모형 자체: 국고채 5·10년 데이터 미수집. 1단계(데이터 확인) 일부만 진행
- 기관 전망 적중률: 평가된 금통위 1회(10/22), 모두 방향 전망이라 Brier·LogLoss 없음, 순위 없음
- 이벤트 전후 가격·발표 시각을 확보하지 못해 확률 변화는 일간 단위만 본다
- 발언·통방문 분석은 키워드·표현 사전 규칙이라 문장 의미 변화를 모두 잡지 못한다
- 전체 이용자용 디자인 재편(카드 축소 등)은 하지 않았다. 기존 화면에 블록을 추가하는 방식

## 확률 계산
공식 확률 산출 로직은 변경하지 않았다(AI 뉴스 압력만 화이트리스트·중복 제거 영향).

## 배포 전 확인
- CSS·JS 캐시 태그(`style.css?v=`, `app.js?v=`)를 올려 두었다.
- 새 분류 필드(`source_type`)는 `run_daily.py`를 한 번 돌려야 채워진다.
